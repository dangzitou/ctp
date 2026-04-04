-- CTP Futures Database Schema
CREATE DATABASE IF NOT EXISTS ctp_futures CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ctp_futures;

-- 合约基础信息表
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id VARCHAR(32) PRIMARY KEY COMMENT '合约代码，如cu2605',
    exchange VARCHAR(16) NOT NULL COMMENT '交易所代码:SHFE/DCE/CZCE/CFFEX/INE',
    name VARCHAR(64) DEFAULT '' COMMENT '合约名称',
    product_code VARCHAR(16) DEFAULT '' COMMENT '品种代码，如cu',
    product_name VARCHAR(64) DEFAULT '' COMMENT '品种名称',
    multiplier DECIMAL(10,2) DEFAULT 1.0 COMMENT '合约乘数',
    tick_size DECIMAL(10,4) DEFAULT 0.01 COMMENT '最小变动价位',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_exchange (exchange)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合约基础信息';

-- Tick行情数据表（按合约分表，便于查询）
CREATE TABLE IF NOT EXISTS ticks (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    instrument_id VARCHAR(32) NOT NULL COMMENT '合约代码',
    last_price DECIMAL(16,4) NOT NULL COMMENT '最新价',
    open_price DECIMAL(16,4) DEFAULT 0 COMMENT '开盘价',
    high_price DECIMAL(16,4) DEFAULT 0 COMMENT '最高价',
    low_price DECIMAL(16,4) DEFAULT 0 COMMENT '最低价',
    bid_price DECIMAL(16,4) DEFAULT 0 COMMENT '买价',
    ask_price DECIMAL(16,4) DEFAULT 0 COMMENT '卖价',
    bid_volume INT DEFAULT 0 COMMENT '买量',
    ask_volume INT DEFAULT 0 COMMENT '卖量',
    volume INT DEFAULT 0 COMMENT '成交量',
    open_interest BIGINT DEFAULT 0 COMMENT '持仓量',
    update_time DATETIME(3) NOT NULL COMMENT '更新时间(毫秒)',
    trading_day DATE NOT NULL COMMENT '交易日',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_instrument_time (instrument_id, update_time DESC),
    INDEX idx_trading_day (trading_day),
    INDEX idx_update_time (update_time DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Tick行情数据';

-- K线数据表（1分钟K线）
CREATE TABLE IF NOT EXISTS klines_1min (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    instrument_id VARCHAR(32) NOT NULL,
    trading_day DATE NOT NULL,
    open_time DATETIME(3) NOT NULL COMMENT 'K线开始时间',
    open_price DECIMAL(16,4) NOT NULL,
    high_price DECIMAL(16,4) NOT NULL,
    low_price DECIMAL(16,4) NOT NULL,
    close_price DECIMAL(16,4) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    turnover DECIMAL(20,4) DEFAULT 0 COMMENT '成交额',
    open_interest BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_inst_time (instrument_id, open_time),
    INDEX idx_trading_day (trading_day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='1分钟K线';

-- 统计信息表（按交易日汇总）
CREATE TABLE IF NOT EXISTS daily_stats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    instrument_id VARCHAR(32) NOT NULL,
    trading_day DATE NOT NULL,
    open_price DECIMAL(16,4) DEFAULT 0 COMMENT '开盘价',
    high_price DECIMAL(16,4) DEFAULT 0 COMMENT '最高价',
    low_price DECIMAL(16,4) DEFAULT 0 COMMENT '最低价',
    close_price DECIMAL(16,4) DEFAULT 0 COMMENT '收盘价',
    volume BIGINT DEFAULT 0 COMMENT '成交量',
    turnover DECIMAL(20,4) DEFAULT 0 COMMENT '成交额',
    open_interest BIGINT DEFAULT 0 COMMENT '持仓量',
    price_change DECIMAL(16,4) DEFAULT 0 COMMENT '涨跌额',
    change_pct DECIMAL(10,4) DEFAULT 0 COMMENT '涨跌幅',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_inst_day (instrument_id, trading_day),
    INDEX idx_trading_day (trading_day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日统计';

-- 系统运行日志表
CREATE TABLE IF NOT EXISTS system_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    level VARCHAR(16) DEFAULT 'INFO',
    source VARCHAR(64) DEFAULT '',
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_level_time (level, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统日志';
