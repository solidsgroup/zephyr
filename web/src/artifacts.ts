export function isVideoContentType(contentType: string) {
  return contentType.toLowerCase().split(";", 1)[0].trim().startsWith("video/");
}

export function isVisualContentType(contentType: string) {
  const normalized = contentType.toLowerCase().split(";", 1)[0].trim();
  return normalized.startsWith("image/") || normalized.startsWith("video/");
}
