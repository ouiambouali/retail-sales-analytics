-- Customers whose net sales are zero or negative (HAVING filters groups after SUM).
SELECT i.customer_id,
       ROUND(SUM(CASE WHEN i.is_cancellation = 0 THEN l.quantity * l.price ELSE 0 END), 2) AS sales,
       ROUND(SUM(CASE WHEN i.is_cancellation = 1 THEN l.quantity * l.price ELSE 0 END), 2) AS cancellations,
       ROUND(SUM(l.quantity * l.price), 2) AS net,
       MIN(i.invoice_date) AS first_date
FROM invoice_lines AS l
JOIN invoices AS i ON i.invoice_no = l.invoice_no
WHERE l.is_sale = 1 AND i.customer_id IS NOT NULL
GROUP BY i.customer_id
HAVING SUM(l.quantity * l.price) <= 0
ORDER BY net;