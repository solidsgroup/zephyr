const pathFieldPattern = /(?:^|\b)(?:path|directory|folder|file|location)(?:\b|$)/i;
const pathValuePattern = /^(?:[a-z]:[\\/]|[.~]{0,2}[\\/]|\\\\)/i;
const urlPattern = /^[a-z][a-z0-9+.-]*:\/\//i;

function looksLikePath(value: string) {
  if (urlPattern.test(value)) return false;
  return pathValuePattern.test(value)
    || (!/\s/.test(value) && (value.includes("/") || value.includes("\\")));
}

function pathParts(value: string) {
  if (!value || urlPattern.test(value) || /[\r\n]/.test(value)) return null;
  const parts = value.split(/[\\/]+/).filter(Boolean);
  return parts.length > 1 ? parts : null;
}

function compactSinglePath(value: string, parts: string[]) {
  if (parts.length <= 3) return value;
  const separator = value.includes("\\") && !value.includes("/") ? "\\" : "/";
  return ["…", ...parts.slice(-2)].join(separator);
}

export function compactPathValues(key: string, values: string[]) {
  const populated = values.filter(Boolean);
  const pathLike = pathFieldPattern.test(key.replaceAll("_", " "))
    || (populated.length > 0 && populated.every(looksLikePath));
  if (!pathLike || !populated.length) return values;

  const parsed = values.map((value) => value ? pathParts(value) : null);
  const populatedParts = parsed.filter((parts): parts is string[] => parts !== null);
  if (populatedParts.length !== populated.length) return values;
  if (populatedParts.length === 1) {
    return values.map((value, index) => value ? compactSinglePath(value, parsed[index]!) : value);
  }

  const shortest = Math.min(...populatedParts.map((parts) => parts.length));
  let commonPrefix = 0;
  while (
    commonPrefix < shortest - 1
    && populatedParts.every((parts) => parts[commonPrefix] === populatedParts[0][commonPrefix])
  ) commonPrefix += 1;

  let commonSuffix = 0;
  while (
    commonSuffix < shortest - commonPrefix - 1
    && populatedParts.every((parts) => parts.at(-commonSuffix - 1) === populatedParts[0].at(-commonSuffix - 1))
  ) commonSuffix += 1;

  if (!commonPrefix && !commonSuffix) return values;
  return values.map((value, index) => {
    if (!value) return value;
    const parts = parsed[index]!;
    const separator = value.includes("\\") && !value.includes("/") ? "\\" : "/";
    const end = commonSuffix ? parts.length - commonSuffix : parts.length;
    return [
      ...(commonPrefix ? ["…"] : []),
      ...parts.slice(commonPrefix, end),
      ...(commonSuffix ? ["…"] : []),
    ].join(separator);
  });
}
