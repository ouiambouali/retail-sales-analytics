-- Net sales per customer (rows with a customer ID only).
SELECT i.customer_id,
       COUNT(DISTINCT CASE WHEN i.is_cancellation = 0 THEN i.invoice_no END) AS invoices,
       ROUND(SUM(l.quantity * l.price), 2) AS net_sales,
       ROUND(100.0 * SUM(l.quantity * l.price) /
             (SELECT SUM(l2.quantity * l2.price)
              FROM invoice_lines AS l2
              JOIN invoices AS i2 ON i2.invoice_no = l2.invoice_no
              WHERE l2.is_sale = 1 AND i2.customer_id IS NOT NULL), 2) AS pct_of_customer_sales
FROM invoice_lines AS l
JOIN invoices AS i ON i.invoice_no = l.invoice_no
WHERE l.is_sale = 1 AND i.customer_id IS NOT NULL
GROUP BY i.customer_id
ORDER BY net_sales DESC;