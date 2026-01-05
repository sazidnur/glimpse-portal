# Glimpse News REST API

REST API for WordPress news integration.

## Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/news/` | GET | Token | Latest 20 news |
| `/api/health/` | GET | No | Health check |

## Authentication

Include the token in the `Authorization` header:

```
Authorization: Token your-api-token-here
```

### Example Request

**cURL:**
```bash
curl -H "Authorization: Token abc123..." https://glimpseapp.net/portal/api/news/
```

## Setup

1. **Create Token in Django Admin:**
   - Go to Admin → AUTH TOKEN → Tokens
   - Click Add Token, select a user, Save
   - Copy the token key

2. **Configure WordPress Plugin:**
   - API URL: `https://glimpseapp.net/portal`
   - API Token: (paste the token)

3. **Configure IP Whitelist (.env):**
   ```env
   ALLOWED_API_IPS=*              # Development
   ALLOWED_API_IPS=123.456.789.0  # Production
   ```

## Response Format

```json
[
    {
        "title": "News headline here",
        "summary": "Brief summary of the article...",
        "source": "https://prothomalo.com/article/123",
        "imageurl": "https://cdn.example.com/image.jpg",
        "time_ago": "5 mins ago"
    }
]
```

## WordPress Shortcode

```
[glimpse_news]              <!-- Latest 20 news -->
[glimpse_news limit="10"]   <!-- Limit to 10 items -->
```
