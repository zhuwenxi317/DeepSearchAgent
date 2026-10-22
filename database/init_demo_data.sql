SET NAMES utf8mb4;
SET time_zone = '+08:00';

-- This seed owns only these four demo tables and is safe to rerun.
DROP TABLE IF EXISTS sales_records;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS warehouses;

CREATE TABLE warehouses (
    warehouse_id TINYINT UNSIGNED NOT NULL,
    warehouse_code VARCHAR(20) NOT NULL,
    warehouse_name VARCHAR(100) NOT NULL,
    region VARCHAR(20) NOT NULL,
    province VARCHAR(50) NOT NULL,
    city VARCHAR(50) NOT NULL,
    address VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '启用',
    created_at DATETIME NOT NULL,
    PRIMARY KEY (warehouse_id),
    UNIQUE KEY uk_warehouses_code (warehouse_code),
    KEY idx_warehouses_region_city (region, city),
    CONSTRAINT chk_warehouses_status CHECK (status IN ('启用', '停用'))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '演示仓库信息';

CREATE TABLE products (
    product_id SMALLINT UNSIGNED NOT NULL,
    sku VARCHAR(40) NOT NULL,
    product_name VARCHAR(150) NOT NULL,
    brand VARCHAR(50) NOT NULL,
    model VARCHAR(80) NOT NULL,
    category VARCHAR(50) NOT NULL,
    unit VARCHAR(10) NOT NULL,
    unit_price DECIMAL(12, 2) NOT NULL,
    cost_price DECIMAL(12, 2) NOT NULL,
    warranty_months SMALLINT UNSIGNED NOT NULL,
    ragflow_document VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '在售',
    created_at DATETIME NOT NULL,
    PRIMARY KEY (product_id),
    UNIQUE KEY uk_products_sku (sku),
    KEY idx_products_name (product_name),
    KEY idx_products_category_name (category, product_name),
    CONSTRAINT chk_products_price
        CHECK (unit_price >= 0 AND cost_price >= 0 AND unit_price >= cost_price),
    CONSTRAINT chk_products_status CHECK (status IN ('在售', '停售'))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '演示产品信息';

CREATE TABLE inventory (
    inventory_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_id SMALLINT UNSIGNED NOT NULL,
    warehouse_id TINYINT UNSIGNED NOT NULL,
    stock_quantity INT UNSIGNED NOT NULL,
    reserved_quantity INT UNSIGNED NOT NULL DEFAULT 0,
    available_quantity INT GENERATED ALWAYS AS
        (stock_quantity - reserved_quantity) STORED,
    reorder_level INT UNSIGNED NOT NULL,
    safety_stock INT UNSIGNED NOT NULL,
    last_stocktake_date DATE NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (inventory_id),
    UNIQUE KEY uk_inventory_product_warehouse (product_id, warehouse_id),
    KEY idx_inventory_product_stock (product_id, stock_quantity),
    KEY idx_inventory_warehouse_stock (warehouse_id, stock_quantity),
    CONSTRAINT fk_inventory_product
        FOREIGN KEY (product_id) REFERENCES products (product_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_inventory_warehouse
        FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT chk_inventory_quantities
        CHECK (reserved_quantity <= stock_quantity),
    CONSTRAINT chk_inventory_levels
        CHECK (reorder_level >= safety_stock)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '演示产品库存';

CREATE TABLE sales_records (
    sale_id BIGINT UNSIGNED NOT NULL,
    order_no VARCHAR(30) NOT NULL,
    sale_date DATE NOT NULL,
    product_id SMALLINT UNSIGNED NOT NULL,
    warehouse_id TINYINT UNSIGNED NOT NULL,
    region VARCHAR(20) NOT NULL,
    sales_channel VARCHAR(30) NOT NULL,
    customer_type VARCHAR(30) NOT NULL,
    quantity SMALLINT UNSIGNED NOT NULL,
    unit_price DECIMAL(12, 2) NOT NULL,
    discount_rate DECIMAL(5, 4) NOT NULL,
    sale_amount DECIMAL(14, 2) GENERATED ALWAYS AS
        (ROUND(quantity * unit_price * discount_rate, 2)) STORED,
    salesperson VARCHAR(50) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (sale_id),
    UNIQUE KEY uk_sales_records_order_no (order_no),
    KEY idx_sales_records_date (sale_date),
    KEY idx_sales_records_product_date (product_id, sale_date),
    KEY idx_sales_records_warehouse_date (warehouse_id, sale_date),
    KEY idx_sales_records_channel_date (sales_channel, sale_date),
    CONSTRAINT fk_sales_records_product
        FOREIGN KEY (product_id) REFERENCES products (product_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_sales_records_warehouse
        FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT chk_sales_records_quantity CHECK (quantity > 0),
    CONSTRAINT chk_sales_records_unit_price CHECK (unit_price >= 0),
    CONSTRAINT chk_sales_records_discount
        CHECK (discount_rate > 0 AND discount_rate <= 1)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '演示产品销售流水';

START TRANSACTION;

INSERT INTO warehouses
    (warehouse_id, warehouse_code, warehouse_name, region, province, city,
     address, status, created_at)
VALUES
    (1, 'WH-BJ-01', '华北中心仓', '华北', '北京市', '北京市',
     '北京市大兴区测试园区 1 号', '启用', '2026-01-01 08:00:00'),
    (2, 'WH-SH-01', '华东中心仓', '华东', '上海市', '上海市',
     '上海市嘉定区测试园区 2 号', '启用', '2026-01-01 08:00:00'),
    (3, 'WH-GZ-01', '华南中心仓', '华南', '广东省', '广州市',
     '广州市黄埔区测试园区 3 号', '启用', '2026-01-01 08:00:00'),
    (4, 'WH-CD-01', '西南中心仓', '西南', '四川省', '成都市',
     '成都市双流区测试园区 4 号', '启用', '2026-01-01 08:00:00'),
    (5, 'WH-WH-01', '华中中心仓', '华中', '湖北省', '武汉市',
     '武汉市东西湖区测试园区 5 号', '启用', '2026-01-01 08:00:00');

INSERT INTO products
    (product_id, sku, product_name, brand, model, category, unit,
     unit_price, cost_price, warranty_months, ragflow_document, status, created_at)
VALUES
    (1, 'HUAWEI-W585X', '华为擎云 W585X 台式计算机', '华为', 'W585X',
     '台式计算机', '台', 5799.00, 4680.00, 36,
     '华为擎云W585X 用户指南-(PGUX,KOS&UOS_02,zh-cn).pdf', '在售', '2026-01-01 09:00:00'),
    (2, 'HUAWEI-B3-243H', '华为显示器 B3-243H', '华为', 'B3-243H',
     '显示器', '台', 899.00, 610.00, 36,
     '华为显示器 B3-243H 用户指南-(SSNB-24BZ,01,zh-cn).pdf', '在售', '2026-01-01 09:00:00'),
    (3, 'RS-12-METER', 'RS-12 数字万用表', 'RS', 'RS-12',
     '检测仪表', '台', 268.00, 160.00, 12,
     '万用表RS-12的使用.pdf', '在售', '2026-01-01 09:00:00'),
    (4, 'XUNRAO-XIAOMI-GW', '迅饶网关与小米设备通讯集成方案', '迅饶', 'XR-XM-GW-SOLUTION',
     '物联网集成方案', '套', 3999.00, 2500.00, 12,
     '迅饶网关与小米产品通讯配置说明.pdf', '在售', '2026-01-01 09:00:00');

-- Every product is stocked in every warehouse: 4 x 5 = 20 rows.
INSERT INTO inventory
    (product_id, warehouse_id, stock_quantity, reserved_quantity,
     reorder_level, safety_stock, last_stocktake_date, updated_at)
SELECT
    p.product_id,
    w.warehouse_id,
    18 + MOD(p.product_id * 29 + w.warehouse_id * 17, 103),
    MOD(p.product_id * 7 + w.warehouse_id * 3, 9),
    30 + p.product_id * 4,
    12 + w.warehouse_id * 2,
    DATE_ADD('2026-08-01', INTERVAL MOD(p.product_id * 3 + w.warehouse_id, 18) DAY),
    DATE_ADD('2026-08-01 09:00:00', INTERVAL p.product_id * w.warehouse_id HOUR)
FROM products AS p
CROSS JOIN warehouses AS w
ORDER BY p.product_id, w.warehouse_id;

-- The product/warehouse formulas cover all 20 pairs ten times: 20 x 10 = 200 rows.
INSERT INTO sales_records
    (sale_id, order_no, sale_date, product_id, warehouse_id, region,
     sales_channel, customer_type, quantity, unit_price, discount_rate,
     salesperson, created_at)
WITH RECURSIVE sequence_numbers AS (
    SELECT 1 AS n
    UNION ALL
    SELECT n + 1
    FROM sequence_numbers
    WHERE n < 200
),
prepared_sales AS (
    SELECT
        n,
        1 + MOD(n - 1, 4) AS product_id,
        1 + MOD(FLOOR((n - 1) / 4), 5) AS warehouse_id,
        1 + MOD(n * 7, 5) AS quantity,
        CAST(
            CASE MOD(n - 1, 5)
                WHEN 0 THEN 1.0000
                WHEN 1 THEN 0.9800
                WHEN 2 THEN 0.9500
                WHEN 3 THEN 0.9200
                ELSE 0.9000
            END AS DECIMAL(5, 4)
        ) AS discount_rate
    FROM sequence_numbers
)
SELECT
    ps.n,
    CONCAT('SO2026', LPAD(ps.n, 6, '0')),
    DATE_ADD('2026-01-01', INTERVAL MOD((ps.n - 1) * 13, 233) DAY),
    p.product_id,
    w.warehouse_id,
    w.region,
    CASE MOD(ps.n + FLOOR((ps.n - 1) / 4), 4)
        WHEN 0 THEN '直营网店'
        WHEN 1 THEN '渠道经销'
        WHEN 2 THEN '企业直销'
        ELSE '项目集成'
    END,
    CASE MOD(ps.n + FLOOR((ps.n - 1) / 5), 3)
        WHEN 0 THEN '个人客户'
        WHEN 1 THEN '企业客户'
        ELSE '政府/事业单位'
    END,
    ps.quantity,
    p.unit_price,
    ps.discount_rate,
    CONCAT('销售专员', LPAD(1 + MOD(ps.n - 1, 10), 2, '0')),
    DATE_ADD(
        DATE_ADD('2026-01-01', INTERVAL MOD((ps.n - 1) * 13, 233) DAY),
        INTERVAL 9 + MOD(ps.n, 9) HOUR
    )
FROM prepared_sales AS ps
JOIN products AS p ON p.product_id = ps.product_id
JOIN warehouses AS w ON w.warehouse_id = ps.warehouse_id
ORDER BY ps.n;

COMMIT;

-- Exact row-count acceptance checks.
SELECT
    counts.table_name,
    counts.row_count,
    counts.expected_count,
    IF(counts.row_count = counts.expected_count, 'PASS', 'FAIL') AS status
FROM (
    SELECT 'warehouses' AS table_name, COUNT(*) AS row_count, 5 AS expected_count
    FROM warehouses
    UNION ALL
    SELECT 'products', COUNT(*), 4 FROM products
    UNION ALL
    SELECT 'inventory', COUNT(*), 20 FROM inventory
    UNION ALL
    SELECT 'sales_records', COUNT(*), 200 FROM sales_records
) AS counts;

-- All foreign-key orphan counts must be zero.
SELECT
    orphan_counts.*,
    IF(
        orphan_counts.inventory_product_orphans
        + orphan_counts.inventory_warehouse_orphans
        + orphan_counts.sales_product_orphans
        + orphan_counts.sales_warehouse_orphans = 0,
        'PASS',
        'FAIL'
    ) AS status
FROM (
    SELECT
        (SELECT COUNT(*)
         FROM inventory AS i
         LEFT JOIN products AS p ON p.product_id = i.product_id
         WHERE p.product_id IS NULL) AS inventory_product_orphans,
        (SELECT COUNT(*)
         FROM inventory AS i
         LEFT JOIN warehouses AS w ON w.warehouse_id = i.warehouse_id
         WHERE w.warehouse_id IS NULL) AS inventory_warehouse_orphans,
        (SELECT COUNT(*)
         FROM sales_records AS s
         LEFT JOIN products AS p ON p.product_id = s.product_id
         WHERE p.product_id IS NULL) AS sales_product_orphans,
        (SELECT COUNT(*)
         FROM sales_records AS s
         LEFT JOIN warehouses AS w ON w.warehouse_id = s.warehouse_id
         WHERE w.warehouse_id IS NULL) AS sales_warehouse_orphans
) AS orphan_counts;

-- Coverage checks prove all product/warehouse combinations are represented.
SELECT
    COUNT(*) AS inventory_rows,
    COUNT(DISTINCT product_id, warehouse_id) AS inventory_pair_coverage,
    IF(COUNT(*) = 20 AND COUNT(DISTINCT product_id, warehouse_id) = 20,
       'PASS', 'FAIL') AS status
FROM inventory;

SELECT
    COUNT(*) AS sales_pair_coverage,
    MIN(pair_transaction_count) AS min_transactions_per_pair,
    MAX(pair_transaction_count) AS max_transactions_per_pair,
    IF(COUNT(*) = 20 AND MIN(pair_transaction_count) = 10
       AND MAX(pair_transaction_count) = 10, 'PASS', 'FAIL') AS status
FROM (
    SELECT product_id, warehouse_id, COUNT(*) AS pair_transaction_count
    FROM sales_records
    GROUP BY product_id, warehouse_id
) AS sales_pairs;

-- Representative aggregates for database-agent smoke testing.
SELECT
    p.product_id,
    p.product_name,
    COUNT(*) AS transaction_count,
    SUM(s.quantity) AS units_sold,
    ROUND(SUM(s.sale_amount), 2) AS sales_revenue
FROM sales_records AS s
JOIN products AS p ON p.product_id = s.product_id
GROUP BY p.product_id, p.product_name
ORDER BY sales_revenue DESC;

SELECT
    p.product_id,
    p.product_name,
    SUM(i.stock_quantity) AS total_stock,
    SUM(i.reserved_quantity) AS total_reserved,
    SUM(i.available_quantity) AS total_available,
    SUM(i.available_quantity < i.reorder_level) AS low_stock_warehouses
FROM inventory AS i
JOIN products AS p ON p.product_id = i.product_id
GROUP BY p.product_id, p.product_name
ORDER BY p.product_id;
