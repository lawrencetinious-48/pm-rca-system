import time

class LoginThrottleStore:
    def __init__(self, max_attempts, window_seconds, lockout_seconds, redis_client=None):
        self.max_attempts = int(max_attempts)
        self.window_seconds = int(window_seconds)
        self.lockout_seconds = int(lockout_seconds)
        self.redis = redis_client
        self._memory = {}

    def get_lockout_seconds(self, key):
        now = int(time.time())
        if self.redis is not None:
            state = self.redis.hgetall(key)
            if not state:
                return 0
            locked_until = int(state.get("locked_until", "0") or 0)
            if locked_until <= now:
                self.redis.delete(key)
                return 0
            return max(1, locked_until - now)
        state = self._memory.get(key)
        if not state:
            return 0
        locked_until = int(state.get("locked_until", 0) or 0)
        if locked_until <= now:
            self._memory.pop(key, None)
            return 0
        return max(1, locked_until - now)

    def register_failure(self, key):
        now = int(time.time())
        if self.redis is not None:
            state = self.redis.hgetall(key)
            first_attempt = int(state.get("first_attempt", "0") or 0)
            count = int(state.get("count", "0") or 0)
            if not state or (now - first_attempt) > self.window_seconds:
                count = 1
                first_attempt = now
                locked_until = 0
            else:
                count += 1
                locked_until = int(state.get("locked_until", "0") or 0)
                if count >= self.max_attempts:
                    locked_until = now + self.lockout_seconds
            self.redis.hset(
                key,
                mapping={
                    "count": count,
                    "first_attempt": first_attempt,
                    "locked_until": locked_until,
                },
            )
            self.redis.expire(key, self.window_seconds + self.lockout_seconds + 60)
            return
        state = self._memory.get(key)
        if not state or (now - int(state["first_attempt"])) > self.window_seconds:
            self._memory[key] = {"count": 1, "first_attempt": now, "locked_until": 0}
            return
        state["count"] += 1
        if state["count"] >= self.max_attempts:
            state["locked_until"] = now + self.lockout_seconds

    def reset(self, key):
        if self.redis is not None:
            self.redis.delete(key)
            return
        self._memory.pop(key, None)
