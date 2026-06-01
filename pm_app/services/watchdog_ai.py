#!/usr/bin/env python3
"""AI-style monitoring engine for the PM/RCA Watchdog."""

import os
import re
import sqlite3
import statistics
import time
from collections import Counter

import requests


class WatchdogBrain:
    """Adaptive monitoring and signal correlation engine."""

    DEFAULT_HISTORY_DB = 'logs/watchdog_history.db'

    def __init__(self, config):
        self.config = config or {}
        self.history_db = os.path.abspath(
            self.config.get('watchdog_history_path')
            or os.getenv('WATCHDOG_HISTORY_DB')
            or self.DEFAULT_HISTORY_DB
        )
        self.thresholds = self.config.get('thresholds', {})
        self.min_history_samples = int(os.getenv('WATCHDOG_MIN_HISTORY_SAMPLES', '8'))
        self.anomaly_factor = float(os.getenv('WATCHDOG_ANOMALY_STD_FACTOR', '2.5'))
        self.forecast_horizon_minutes = int(os.getenv('WATCHDOG_FORECAST_HORIZON_MINUTES', '30'))
        self.window_hours = int(os.getenv('WATCHDOG_HISTORY_WINDOW_HOURS', '720'))
        self.prometheus_url = self.config.get('prometheus_url') or os.getenv('PROMETHEUS_URL')
        self.loki_url = self.config.get('loki_url') or os.getenv('LOKI_URL')
        self.prometheus_enabled = bool(self.prometheus_url)
        self.loki_enabled = bool(self.loki_url)
        self._ensure_history_store()

    def _ensure_history_store(self):
        os.makedirs(os.path.dirname(self.history_db), exist_ok=True)
        self.conn = sqlite3.connect(self.history_db, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_samples (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                timestamp REAL NOT NULL,
                value REAL NOT NULL,
                tags TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS log_clusters (
                id INTEGER PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                count INTEGER NOT NULL,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL
            )
            """
        )
        self.conn.commit()

    def _execute(self, statement, params=(), commit=False):
        cursor = self.conn.cursor()
        cursor.execute(statement, params)
        if commit:
            self.conn.commit()
        return cursor

    def append_metric(self, name, value, tags=None):
        try:
            self._execute(
                'INSERT INTO metric_samples (name, timestamp, value, tags) VALUES (?, ?, ?, ?)',
                (name, time.time(), float(value), tags or ''),
                commit=True
            )
            self._trim_old_samples()
        except Exception:
            pass

    def _trim_old_samples(self):
        cutoff = time.time() - self.window_hours * 3600
        self._execute('DELETE FROM metric_samples WHERE timestamp < ?', (cutoff,), commit=True)

    def get_series(self, name, max_samples=200):
        cutoff = time.time() - self.window_hours * 3600
        rows = self._execute(
            'SELECT timestamp, value FROM metric_samples WHERE name = ? AND timestamp >= ? ORDER BY timestamp ASC',
            (name, cutoff)
        ).fetchall()
        return [(float(ts), float(value)) for ts, value in rows][-max_samples:]

    def compute_baseline(self, series):
        if not series or len(series) < self.min_history_samples:
            return None
        values = [value for _, value in series]
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        return {'mean': mean, 'stdev': stdev, 'count': len(values)}

    def forecast_value(self, series):
        if not series or len(series) < 4:
            return None
        points = [(timestamp / 60.0, value) for timestamp, value in series]
        x = [p[0] for p in points]
        y = [p[1] for p in points]
        n = len(x)
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        denom = sum((xi - mean_x) ** 2 for xi in x)
        if denom == 0:
            return None
        slope = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / denom
        intercept = mean_y - slope * mean_x
        future_minutes = (time.time() / 60.0) + self.forecast_horizon_minutes
        return intercept + slope * future_minutes

    def normalize_message(self, message):
        if not message:
            return None
        raw = str(message)
        match = re.search(r'([-+]?[0-9]*\.?[0-9]+)', raw)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _error_fingerprint(self, text):
        if not text:
            return ''
        text = re.sub(r'\d+', '<num>', text)
        text = re.sub(r'https?://\S+', '<url>', text, flags=re.IGNORECASE)
        text = re.sub(r'"[^"]*"', '"<str>"', text)
        return text.strip()[:320]

    def analyze_logs(self, log_path, max_lines=500):
        lines = []
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()[-max_lines:]
            except Exception:
                lines = []

        if not lines and self.loki_enabled:
            lines = self._fetch_loki_error_lines(max_lines)

        error_lines = [line.strip() for line in lines if 'ERROR' in line or 'CRITICAL' in line]
        if not error_lines:
            return None

        clusters = Counter()
        for line in error_lines:
            fingerprint = self._error_fingerprint(line)
            if fingerprint:
                clusters[fingerprint] += 1

        top = clusters.most_common(5)
        clusters_summary = [
            {'count': count, 'pattern': fingerprint}
            for fingerprint, count in top
        ]
        return {
            'error_count': len(error_lines),
            'top_clusters': clusters_summary,
        }

    def _fetch_prometheus_series(self, promql, duration_sec=3600, step_sec=60):
        if not self.prometheus_enabled or not promql:
            return None
        try:
            end_ts = time.time()
            start_ts = end_ts - duration_sec
            params = {
                'query': promql,
                'start': f"{start_ts:.0f}",
                'end': f"{end_ts:.0f}",
                'step': f"{step_sec}s",
            }
            response = requests.get(f"{self.prometheus_url.rstrip('/')}/api/v1/query_range", params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('status') != 'success':
                return None
            values = data.get('data', {}).get('result', [])
            if not values:
                return None
            series = []
            for sample in values[0].get('values', []):
                ts, val = sample
                try:
                    series.append((float(ts), float(val)))
                except Exception:
                    continue
            return series
        except Exception:
            return None

    def _fetch_loki_error_lines(self, max_lines):
        if not self.loki_enabled:
            return []
        try:
            end_ts = int(time.time() * 1_000_000_000)
            start_ts = end_ts - (60 * 60 * 1_000_000_000)
            query = 'level="ERROR" OR level="CRITICAL" OR ERROR OR CRITICAL'
            params = {
                'query': query,
                'start': str(start_ts),
                'end': str(end_ts),
                'limit': str(max_lines),
            }
            # Retry loop to handle transient network or Loki errors
            payload = None
            for attempt in range(3):
                try:
                    resp = requests.get(f"{self.loki_url.rstrip('/')}/loki/api/v1/query_range", params=params, timeout=10)
                    resp.raise_for_status()
                    payload = resp.json()
                    break
                except requests.RequestException:
                    # exponential backoff between attempts
                    if attempt < 2:
                        time.sleep(0.5 * (2 ** attempt))
                        continue
                    return []
            entries = []
            for stream in payload.get('data', {}).get('result', []):
                for ts, line in stream.get('values', []):
                    entries.append(line)
            return entries[-max_lines:]
        except Exception:
            return []

    def detect_anomaly(self, name, current, series):
        baseline = self.compute_baseline(series)
        if baseline is None or baseline['stdev'] <= 0:
            return None
        deviation = current - baseline['mean']
        score = deviation / baseline['stdev'] if baseline['stdev'] > 0 else 0.0
        if score >= self.anomaly_factor:
            return {
                'type': 'high_deviation',
                'mean': baseline['mean'],
                'stdev': baseline['stdev'],
                'score': score,
                'message': f"{name} is {current:.2f}, which is {score:.1f} standard deviations above recent baseline {baseline['mean']:.2f}."
            }
        return None

    def detect_bottleneck(self, metric_name, series, threshold_percentile=90):
        """Detect operational bottlenecks in review or approval times.
        
        Args:
            metric_name: Name of the metric (e.g., 'review_time_hours')
            series: List of (timestamp, value) tuples
            threshold_percentile: Percentile to consider as bottleneck (default 90th)
        
        Returns:
            Dict with bottleneck info if detected, else None
        """
        if not series or len(series) < 5:
            return None
        
        values = sorted([value for _, value in series])
        threshold_idx = int(len(values) * (threshold_percentile / 100))
        threshold = values[threshold_idx] if threshold_idx < len(values) else values[-1]
        
        # Check if recent values are above threshold
        recent_values = [value for _, value in series[-10:]]
        above_threshold = sum(1 for v in recent_values if v > threshold)
        
        if above_threshold >= 6:  # 60% of recent samples above threshold
            return {
                'type': 'bottleneck_detected',
                'metric': metric_name,
                'threshold': threshold,
                'recent_average': statistics.mean(recent_values),
                'message': f"Bottleneck in {metric_name}: recent average ({statistics.mean(recent_values):.1f}) exceeds {threshold_percentile}th percentile ({threshold:.1f})."
            }
        return None

    def detect_trend_change(self, name, series, window_size=10):
        """Detect significant trend changes in metrics.
        
        Args:
            name: Metric name
            series: List of (timestamp, value) tuples
            window_size: Size of historical window for comparison
        
        Returns:
            Dict with trend change info if detected, else None
        """
        if not series or len(series) < window_size * 2:
            return None
        
        values = [value for _, value in series]
        recent = values[-window_size:]
        historical = values[-(window_size * 2):-window_size]
        
        recent_mean = statistics.mean(recent)
        historical_mean = statistics.mean(historical)
        
        if historical_mean == 0:
            return None
        
        pct_change = abs((recent_mean - historical_mean) / historical_mean) * 100
        
        if pct_change > 30:  # >30% change is significant
            direction = "increase" if recent_mean > historical_mean else "decrease"
            return {
                'type': 'trend_change',
                'metric': name,
                'pct_change': pct_change,
                'direction': direction,
                'message': f"Significant {direction} in {name}: {pct_change:.1f}% change detected."
            }
        return None

    def classify_form_risk(self, form_data):
        """Classify form risk level based on multiple factors.
        
        Args:
            form_data: Dict with form metadata (type, complexity, rejection_count, days_pending, etc.)
        
        Returns:
            Dict with risk classification
        """
        risk_score = 0
        risk_factors = []
        
        # Rejection count impact
        rejections = form_data.get('rejection_count', 0)
        if rejections >= 2:
            risk_score += 30
            risk_factors.append(f"Multiple rejections ({rejections})")
        elif rejections == 1:
            risk_score += 15
            risk_factors.append("Previously rejected")
        
        # Days pending impact
        days_pending = form_data.get('days_pending', 0)
        if days_pending > 5:
            risk_score += 25
            risk_factors.append(f"Pending {days_pending} days")
        elif days_pending > 2:
            risk_score += 15
            risk_factors.append(f"Pending {days_pending} days")
        
        # Form complexity
        form_type = form_data.get('form_type', 'pm')
        if form_type == 'rca':
            risk_score += 20
            risk_factors.append("RCA form (inherently complex)")
        
        # Missing data impact
        completeness = form_data.get('field_completeness', 100)
        if completeness < 75:
            risk_score += 20
            risk_factors.append(f"Incomplete ({completeness}% complete)")
        
        # Determine classification
        if risk_score >= 70:
            classification = 'critical'
        elif risk_score >= 40:
            classification = 'high'
        elif risk_score >= 20:
            classification = 'medium'
        else:
            classification = 'low'
        
        return {
            'classification': classification,
            'score': min(risk_score, 100),
            'factors': risk_factors,
            'recommended_action': self._get_risk_recommendation(classification)
        }

    def _get_risk_recommendation(self, classification):
        """Get recommended action for risk classification."""
        recommendations = {
            'critical': 'Escalate immediately; manager review required within 2 hours',
            'high': 'Prioritize for review; assign to senior reviewer if available',
            'medium': 'Standard queue; monitor for further delays',
            'low': 'Standard processing; can batch with other items'
        }
        return recommendations.get(classification, 'Standard processing')

    def suggest_reviewer_assignment(self, form_data, reviewer_stats):
        """Suggest best reviewer for a form based on expertise and load.
        
        Args:
            form_data: Dict with form info (type, complexity, etc.)
            reviewer_stats: Dict of reviewers with stats (approval_rate, avg_time, current_queue_size)
        
        Returns:
            Tuple of (suggested_reviewer_id, recommendation_reason)
        """
        if not reviewer_stats:
            return (None, "No reviewers available")
        
        form_type = form_data.get('form_type', 'pm')
        
        # Score each reviewer
        scored_reviewers = []
        for reviewer_id, stats in reviewer_stats.items():
            score = 0
            
            # Preference for reviewers who handle this form type well
            type_approval_rate = stats.get(f'{form_type}_approval_rate', 50)
            score += type_approval_rate * 0.4  # 40% weight on approval rate
            
            # Preference for less busy reviewers
            queue_size = stats.get('current_queue_size', 0)
            load_penalty = min(queue_size * 5, 50)  # Up to 50 point penalty
            score -= load_penalty
            
            # Preference for faster reviewers
            avg_time = stats.get('avg_review_hours', 24)
            if avg_time < 4:
                score += 15
            elif avg_time > 48:
                score -= 15
            
            scored_reviewers.append((reviewer_id, score, stats))
        
        if not scored_reviewers:
            return (None, "Unable to score reviewers")
        
        scored_reviewers.sort(key=lambda x: x[1], reverse=True)
        best_reviewer_id, best_score, best_stats = scored_reviewers[0]
        
        reason = f"Selected based on {form_type} expertise (rate: {best_stats.get(f'{form_type}_approval_rate', 0)}%) and current load ({best_stats.get('current_queue_size', 0)} items)"
        return (best_reviewer_id, reason)

        if score <= -self.anomaly_factor:
            return {
                'type': 'low_deviation',
                'mean': baseline['mean'],
                'stdev': baseline['stdev'],
                'score': score,
                'message': f"{name} is {current:.2f}, which is {abs(score):.1f} standard deviations below recent baseline {baseline['mean']:.2f}."
            }
        return None

    def predict_threshold_crossing(self, name, current, series, threshold):
        if threshold is None or series is None or len(series) < 4:
            return None
        forecast = self.forecast_value(series)
        if forecast is None:
            return None
        if forecast > threshold:
            return {
                'future_value': forecast,
                'threshold': threshold,
                'horizon_minutes': self.forecast_horizon_minutes,
                'message': f"Forecast indicates {name} may reach {forecast:.2f} in {self.forecast_horizon_minutes} minutes, above threshold {threshold:.2f}."
            }
        return None

    def correlate(self, results):
        problems = [name for name, item in results.items() if item['status'] != 'ok' or item.get('warning')]
        if not problems:
            return 'All monitored signals are within normal ranges.'

        if 'cpu' in problems and 'memory' in problems:
            return 'CPU and memory signals are correlated; system resource pressure is the likely root cause.'
        if 'response_time' in problems and 'database' in problems:
            return 'Response time slowdown coupled with database issues suggests persistence latency or connection exhaustion.'
        if 'response_time' in problems and 'redis' in problems:
            return 'App latency with Redis trouble points to cache or session store degradation affecting request handling.'
        if 'log_errors' in problems and 'response_time' in problems:
            return 'Error spikes alongside response time warnings indicate an application-level failure rather than pure infrastructure load.'
        if 'disk' in problems and 'memory' in problems:
            return 'Disk pressure and memory pressure can both arise from heavy log or swap usage; investigate I/O and local storage consumption.'
        if 'network' in problems and 'database' in problems:
            return 'Network and database signals together point to connectivity or routing failures affecting persistence access.'
        if len(problems) > 2:
            return 'Multiple subsystems are degraded; this is likely a broader incident rather than an isolated threshold breach.'
        return 'The system is emitting related warnings; review the named subsystems for the most likely failure path.'

    def build_ai_insights(self, results, log_intelligence=None):
        lines = []
        anomalies = []
        predictions = []
        for name, item in results.items():
            if item.get('anomaly'):
                anomalies.append(item['anomaly']['message'])
            if item.get('forecast'):
                predictions.append(item['forecast']['message'])
        correlation = self.correlate(results)
        if anomalies:
            lines.append('Anomaly signals:')
            lines.extend([f'- {line}' for line in anomalies[:3]])
            lines.append('')
        if predictions:
            lines.append('Forecast warnings:')
            lines.extend([f'- {line}' for line in predictions[:3]])
            lines.append('')
        lines.append('Correlation summary:')
        lines.append(f'- {correlation}')
        if log_intelligence:
            log_insight = log_intelligence
            lines.append('')
            lines.append('Log intelligence:')
            lines.append(f"- {log_insight['error_count']} recent errors grouped into {len(log_insight['top_clusters'])} clusters.")
            for cluster in log_insight['top_clusters'][:3]:
                lines.append(f"  · {cluster['count']} events — {cluster['pattern'][:120]}")
        return '\n'.join(lines)

    def analyze_results(self, results):
        metrics = {
            'cpu': ('cpu_percent', 'percent'),
            'memory': ('memory_percent', 'percent'),
            'disk': ('disk_percent', 'percent'),
            'response_time': ('response_time_sec', 'seconds'),
            'log_errors': ('max_error_rate', 'fraction'),
        }

        for name, item in results.items():
            if name not in metrics:
                continue
            threshold_key, scale = metrics[name]
            value = self.normalize_message(item.get('message'))
            if value is None:
                continue
            if scale == 'fraction' and '%' in str(item.get('message', '')):
                value = value / 100.0
            self.append_metric(name, value)

            series = self.get_series(name)
            if len(series) < self.min_history_samples and self.prometheus_enabled:
                prom_series = self._fetch_prometheus_series_for_metric(name)
                if prom_series and len(prom_series) >= self.min_history_samples:
                    series = prom_series

            anomaly = self.detect_anomaly(name, value, series)
            forecast = self.predict_threshold_crossing(name, value, series, self.thresholds.get(threshold_key, None))
            if anomaly:
                item['anomaly'] = anomaly
            if forecast:
                item['forecast'] = forecast

        log_path = self.config.get('log_path', 'logs/app.log')
        log_intelligence = self.analyze_logs(log_path)
        anomalies = [item['anomaly'] for item in results.values() if item.get('anomaly')]
        predictions = [item['forecast'] for item in results.values() if item.get('forecast')]
        analysis = {
            'log_intelligence': log_intelligence,
            'anomaly_count': len(anomalies),
            'prediction_count': len(predictions),
            'anomaly_signals': anomalies,
            'forecast_warnings': predictions,
        }
        analysis['ai_summary'] = self.build_ai_insights(results, log_intelligence=log_intelligence)
        return analysis

    def _prometheus_query_for_metric(self, name):
        queries = {
            'cpu': 'avg_over_time(cpu_usage_percent[1h])',
            'memory': 'avg_over_time(memory_usage_percent[1h])',
            'disk': 'avg_over_time(disk_usage_percent[1h])',
            'response_time': 'rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m])',
            'log_errors': None,
        }
        return queries.get(name)

    def _fetch_prometheus_series_for_metric(self, name):
        promql = self._prometheus_query_for_metric(name)
        if not promql:
            return None
        return self._fetch_prometheus_series(promql, duration_sec=min(self.window_hours * 3600, 86400), step_sec=300)
