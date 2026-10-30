-- Net sales, invoices and share of total per country.
SELECT i.country,
       ROUND(SUM(l.quantity * l.price), 2) AS net_sales,
       COUNT(DISTINCT CASE WHEN i.is_cancellation = 0 THEN i.invoice_no END) AS invoices,
       ROUND(100.0 * SUM(l.quantity * l.price) /
             (SELECT SUM(quantity * price) FROM invoice_lines WHERE is_sale = 1), 2) AS pct_of_total
FROM invoice_lines AS l
JOIN invoices AS i ON i.invoice_no = l.invoice_no
WHERE l.is_sale = 1
GROUP BY i.country
ORDER BY net_sales DESC;