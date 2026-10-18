-- ChatBI 初始化（FR-22 / B27）：schema、角色、扩展。幂等（IF NOT EXISTS / DO 守卫）。
-- 注意：不含 dw 业务表 DDL 与 seed（P6 产出）；由 postgres 超级用户在库初始化时执行。

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS dw;

-- 角色创建守卫（幂等）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user LOGIN PASSWORD 'app_password';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chatbi_ro') THEN
        CREATE ROLE chatbi_ro LOGIN PASSWORD 'chatbi_ro_password';
    END IF;
END $$;

-- 默认 search_path：app_user → app；chatbi_ro → dw
ALTER ROLE app_user SET search_path = app;
ALTER ROLE chatbi_ro SET search_path = dw;

-- app_user：schema app 的 USAGE/CREATE（create_all 建表）与全 DML（FR-22）
GRANT USAGE, CREATE ON SCHEMA app TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

-- chatbi_ro：仅 schema dw 的 USAGE + SELECT（含系统目录 information_schema/pg_catalog 天然可读）；
-- 不授予 dw 的 CREATE/写权限、不授予 app 的任何权限（AC-13/B22 物理只读）。
GRANT USAGE ON SCHEMA dw TO chatbi_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA dw
    GRANT SELECT ON TABLES TO chatbi_ro;
