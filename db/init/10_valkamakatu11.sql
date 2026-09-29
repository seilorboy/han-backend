-- Valkamakatu 11 database initialization
--
-- This script is intended for MySQL 8 initialization through
-- /docker-entrypoint-initdb.d on a new, empty database volume.
-- It does not delete existing tables or measurement data.

CREATE DATABASE IF NOT EXISTS Valkamakatu11
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE Valkamakatu11;

CREATE TABLE IF NOT EXISTS apartments (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS meters (
    id INT NOT NULL AUTO_INCREMENT,
    meter_serial VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    usage_point_no VARCHAR(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    role ENUM('load', 'pv_raw', 'consumption_raw')
        COLLATE utf8mb4_unicode_ci NOT NULL,
    apartment_id INT DEFAULT NULL,
    active TINYINT DEFAULT 1,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_usage_point_role (usage_point_no, role),
    KEY apartment_id (apartment_id),
    CONSTRAINT meters_ibfk_1
        FOREIGN KEY (apartment_id) REFERENCES apartments (id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS measurements (
    id INT NOT NULL AUTO_INCREMENT,
    meter_id INT NOT NULL,
    ts DATETIME NOT NULL COMMENT 'UTC timestamp stored without timezone',
    reading_type ENUM('BN01', 'BN02', 'BN03', 'INTERNAL') NOT NULL,
    wh_import DOUBLE DEFAULT 0,
    wh_export DOUBLE DEFAULT 0,
    wh_prod DOUBLE DEFAULT 0,
    wh_consumption DOUBLE DEFAULT 0,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_measurements_meter_ts_type (meter_id, ts, reading_type),
    KEY idx_measurements_ts (ts),
    CONSTRAINT measurements_ibfk_1
        FOREIGN KEY (meter_id) REFERENCES meters (id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

-- Baseline apartment registry. Explicit IDs keep apartment-to-meter mappings
-- deterministic on a new installation. INSERT IGNORE makes accidental reruns
-- harmless when these primary keys already exist.
INSERT IGNORE INTO apartments (id, name) VALUES
    (1,  'Apartment1'),
    (2,  'Apartment2'),
    (3,  'Apartment3'),
    (4,  'Apartment4'),
    (5,  'Apartment5'),
    (6,  'Apartment6'),
    (7,  'Apartment7'),
    (8,  'Apartment8'),
    (9,  'Apartment9'),
    (10, 'Apartment10'),
    (11, 'Apartment11'),
    (12, 'Apartment12'),
    (13, 'Apartment13'),
    (14, 'Apartment14'),
    (15, 'Apartment15'),
    (16, 'Apartment16'),
    (17, 'Apartment17'),
    (18, 'Apartment18'),
    (19, 'Apartment19'),
    (20, 'Apartment20'),
    (21, 'Apartment21'),
    (22, 'Apartment22'),
    (23, 'Apartment23'),
    (24, 'Apartment24');

-- Baseline meters used by the application. PV_MAIN is the property's internal
-- PV production submeter. COMMON_MAIN and APT1-APT24 contain Datahub-derived
-- load series. Replace placeholder usage-point numbers during deployment.
INSERT IGNORE INTO meters
    (id, meter_serial, usage_point_no, role, apartment_id)
VALUES
    (1,  'PV_MAIN',     'UPN_PV',  'pv_raw', NULL),
    (2,  'COMMON_MAIN', 'UPN_COM', 'load',   NULL),
    (3,  'APT1',        'UPN_A1',  'load',   1),
    (4,  'APT2',        'UPN_A2',  'load',   2),
    (5,  'APT3',        'UPN_A3',  'load',   3),
    (6,  'APT4',        'UPN_A4',  'load',   4),
    (7,  'APT5',        'UPN_A5',  'load',   5),
    (8,  'APT6',        'UPN_A6',  'load',   6),
    (9,  'APT7',        'UPN_A7',  'load',   7),
    (10, 'APT8',        'UPN_A8',  'load',   8),
    (11, 'APT9',        'UPN_A9',  'load',   9),
    (12, 'APT10',       'UPN_A10', 'load',   10),
    (13, 'APT11',       'UPN_A11', 'load',   11),
    (14, 'APT12',       'UPN_A12', 'load',   12),
    (15, 'APT13',       'UPN_A13', 'load',   13),
    (16, 'APT14',       'UPN_A14', 'load',   14),
    (17, 'APT15',       'UPN_A15', 'load',   15),
    (18, 'APT16',       'UPN_A16', 'load',   16),
    (19, 'APT17',       'UPN_A17', 'load',   17),
    (20, 'APT18',       'UPN_A18', 'load',   18),
    (21, 'APT19',       'UPN_A19', 'load',   19),
    (22, 'APT20',       'UPN_A20', 'load',   20),
    (23, 'APT21',       'UPN_A21', 'load',   21),
    (24, 'APT22',       'UPN_A22', 'load',   22),
    (25, 'APT23',       'UPN_A23', 'load',   23),
    (26, 'APT24',       'UPN_A24', 'load',   24);
