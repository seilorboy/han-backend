CREATE DATABASE IF NOT EXISTS Valkamakatu11
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE Valkamakatu11;

CREATE TABLE IF NOT EXISTS apartments (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    building_code   VARCHAR(50) NOT NULL DEFAULT 'Valkamakatu11',
    apartment_code  VARCHAR(50) NOT NULL,
    address         VARCHAR(255) NULL,
    floor           TINYINT NULL,
    description     VARCHAR(255) NULL,
    active          TINYINT(1) NOT NULL DEFAULT 1,
    UNIQUE KEY uq_building_apartment (building_code, apartment_code)
) ENGINE=InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS meters (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    usage_point_no  VARCHAR(64) NOT NULL COMMENT 'Datahub usage point ID',
    meter_serial    VARCHAR(64) NULL COMMENT 'Physical meter serial number',
    role ENUM('APARTMENT', 'COMMON', 'PV', 'GRID_IMPORT', 'GRID_EXPORT')
         NOT NULL DEFAULT 'APARTMENT',
    apartment_id INT UNSIGNED NULL,
    active       TINYINT(1) NOT NULL DEFAULT 1,
    installed_at DATETIME NULL,
    removed_at   DATETIME NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_meters_apartment
        FOREIGN KEY (apartment_id) REFERENCES apartments(id),
    UNIQUE KEY uq_usage_point_no  (usage_point_no),
    UNIQUE KEY uq_meter_serial    (meter_serial),
    KEY idx_role_active (role, active)
) ENGINE=InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS measurements (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    meter_id INT UNSIGNED NOT NULL,
    ts       DATETIME(0) NOT NULL,
    wh_import BIGINT NULL COMMENT 'Energy imported from grid / consumption',
    wh_export BIGINT NULL COMMENT 'Energy exported to grid',
    wh_prod   BIGINT NULL COMMENT 'Produced energy (e.g. PV)',
    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_measurements_meter
        FOREIGN KEY (meter_id) REFERENCES meters(id),
    UNIQUE KEY uq_meter_ts (meter_id, ts),
    KEY idx_ts (ts),
    KEY idx_meter_ts (meter_id, ts)
) ENGINE=InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;
