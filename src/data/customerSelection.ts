/** URL state only: no customer content is stored in browser persistence. */
export function readCustomerSelection() {
  try {
    const route = decodeURIComponent(window.location.hash.slice(1));
    const [path, query = ""] = route.split("?");
    const parts = path.split("/");
    const params = new URLSearchParams(query);
    const id = Number(parts[1] === "conversation" ? parts[2]?.split("?")[0] : params.get("conversation"));
    return Number.isInteger(id) && id > 0 ? id : null;
  } catch { return null; }
}

export function customerImagesHash(conversationId: number | null) {
  return `#${encodeURIComponent(`客户消息/images${conversationId ? `?conversation=${conversationId}` : ""}`)}`;
}
