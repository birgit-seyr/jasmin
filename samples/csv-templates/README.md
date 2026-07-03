# CSV upload samples

Sample CSVs for testing the data-list upload feature (`POST /api/commissioning/data-import/`).
Each file uses the three-row template format produced by the
"Download CSV template" button:

    row 0  human-readable titles (ignored on import)
    row 1  field names — the upload schema
    row 2  type hints (ignored on import)
    row 3+ data rows

One row in each file is intentionally invalid so you can verify the
"continue on row failure" behaviour. The endpoint will list it under
`errors[]` while still importing the valid rows.

| File | `model_name` | Page that uploads it | Intentionally-failing row |
|---|---|---|---|
| `share_article.csv` | `share_article` | ListShareArticles | empty `name` |
| `crate.csv` | `crate` | ListCrates *(if wired)* | empty `name` |
| `member.csv` | `member` | Members | invalid `email` |
| `delivery_station.csv` | `delivery_station` | ListDeliveryStations | duplicate `number` |
| `reseller.csv` | `reseller` | ListSellers / ListResellers | duplicate `number` |

## Expected response

```json
{
  "model_name": "share_article",
  "total_rows": 4,
  "successful": 3,
  "failed": 1,
  "results": [
    {"row": 4, "id": "..."},
    {"row": 5, "id": "..."},
    {"row": 6, "id": "..."}
  ],
  "errors": [
    {"row": 7, "error": "name: This field may not be blank.", "data": {...}}
  ]
}
```
