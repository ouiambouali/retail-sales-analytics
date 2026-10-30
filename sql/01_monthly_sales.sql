-- Net sales and invoice count per month (analysis rows only).
SELECT strftime('%Y-%m', i.invoice_date) AS month,
       ROUND(SUM(l.quantity * l.price), 2) AS net_sales,
       COUNT(DISTINCT CASE WHEN i.is_cancellation = 0 THEN i.invoice_no END) AS invoices
FROM invoice_lines AS l
JOIN invoices AS i ON i.invoice_no = l.invoice_no
WHERE l.is_sale = 1
GROUP BY month
ORDER BY month;