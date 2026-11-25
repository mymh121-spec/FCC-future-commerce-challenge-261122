/**
 * API 또는 서버에서 JSON 데이터를 조회한다.
 * 사용 예: const products = await fetchJson("/api/products");
 * 브라우저에서는 상대 경로를, Node.js에서는 전체 URL을 사용할 수 있다.
 */
export async function fetchJson(url, { headers, signal } = {}) {
  const requestHeaders = new Headers(headers);
  if (!requestHeaders.has("Accept")) {
    requestHeaders.set("Accept", "application/json");
  }

  const response = await fetch(url, { headers: requestHeaders, signal });
  if (!response.ok) {
    throw new Error(`API 요청 실패 (HTTP ${response.status})`);
  }

  if (response.status === 204 || response.status === 205) {
    return null;
  }
  return response.json();
}
