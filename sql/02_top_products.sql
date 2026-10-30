-- Top 10 products by net sales, with share of total (subquery for the total).
SELECT p.stock_code,
       p.description,
       SUM(l.quantity) AS units,
       ROUND(SUM(l.quantity * l.price), 2) AS net_sales,
       ROUND(100.0 * SUM(l.quantity * l.price) /
             (SELECT SUM(quantity * price) FROM invoice_lines WHERE is_sale = 1), 2) AS pct_of_total
FROM invoice_lines AS l
JOIN products AS p ON p.stock_code = l.stock_code
WHERE l.is_sale = 1
GROUP BY p.stock_code, p.description
ORDER BY net_sales DESC
LIMIT 10;