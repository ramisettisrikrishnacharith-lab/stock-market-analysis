-- Stock Market Analysis System - MySQL 8.0 schema
-- Run this file in MySQL Workbench, or let init_db.py apply it.
-- The script is safe to re-run: it never drops or truncates existing data.

CREATE DATABASE IF NOT EXISTS stock_market_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE stock_market_db;

CREATE TABLE IF NOT EXISTS stocks (
    stock_id      INT            NOT NULL AUTO_INCREMENT,
    symbol        VARCHAR(20)    NOT NULL,
    company_name  VARCHAR(150)   NOT NULL,
    exchange      VARCHAR(20)    NULL,
    created_at    TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id),
    UNIQUE KEY uq_stocks_symbol (symbol)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stock_prices (
    price_id     BIGINT         NOT NULL AUTO_INCREMENT,
    stock_id     INT            NOT NULL,
    trade_date   DATE           NOT NULL,
    open_price   DECIMAL(15,4)  NULL,
    high_price   DECIMAL(15,4)  NULL,
    low_price    DECIMAL(15,4)  NULL,
    close_price  DECIMAL(15,4)  NULL,
    volume       BIGINT         NULL,
    data_source  VARCHAR(20)    NOT NULL DEFAULT 'yfinance',
    created_at   TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (price_id),
    UNIQUE KEY uq_stock_prices_stock_date (stock_id, trade_date),
    KEY idx_stock_prices_stock_date (stock_id, trade_date),
    KEY idx_stock_prices_trade_date (trade_date),
    CONSTRAINT fk_stock_prices_stock
        FOREIGN KEY (stock_id) REFERENCES stocks (stock_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS watchlist (
    watchlist_id  INT        NOT NULL AUTO_INCREMENT,
    stock_id      INT        NOT NULL,
    created_at    TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (watchlist_id),
    UNIQUE KEY uq_watchlist_stock (stock_id),
    KEY idx_watchlist_stock (stock_id),
    CONSTRAINT fk_watchlist_stock
        FOREIGN KEY (stock_id) REFERENCES stocks (stock_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
