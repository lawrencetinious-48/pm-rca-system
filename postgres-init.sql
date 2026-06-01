-- PM System Database Initialization
-- Creates audit_logs table

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50),
    resource_id INTEGER,
    details TEXT,
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for audit queries
CREATE INDEX IF NOT EXISTS ix_audit_timestamp ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS ix_audit_ip ON audit_logs(ip_address);
CREATE INDEX IF NOT EXISTS ix_audit_category ON audit_logs(category);

-- Insert initial system audit entry
INSERT INTO audit_logs (action, category, details) VALUES 
('system_initialized', 'system', 'Database initialized with audit logs')
ON CONFLICT DO NOTHING;
