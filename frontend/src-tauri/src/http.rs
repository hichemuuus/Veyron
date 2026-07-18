use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct HttpResponse {
    pub status: u16,
    pub ok: bool,
    pub body: String,
}

#[tauri::command]
pub async fn http_fetch(
    url: String,
    method: Option<String>,
    headers: Option<Vec<(String, String)>>,
    body: Option<String>,
    timeout_secs: Option<u64>,
) -> Result<HttpResponse, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(timeout_secs.unwrap_or(30)))
        .build()
        .map_err(|e| format!("failed to build HTTP client: {e}"))?;

    let method = method.as_deref().unwrap_or("GET");
    let req = match method {
        "GET" => client.get(&url),
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "DELETE" => client.delete(&url),
        _ => return Err(format!("unsupported HTTP method: {method}")),
    };

    let req = if let Some(ref h) = headers {
        let mut r = req;
        for (k, v) in h {
            r = r.header(k.as_str(), v.as_str());
        }
        r
    } else {
        req
    };

    let req = if let Some(b) = body {
        req.body(b)
    } else {
        req
    };

    let resp = req.send().await.map_err(|e| format!("HTTP request failed: {e}"))?;
    let status = resp.status().as_u16();
    let ok = resp.status().is_success();
    let resp_body = resp.text().await.map_err(|e| format!("failed to read response body: {e}"))?;

    Ok(HttpResponse { status, ok, body: resp_body })
}
