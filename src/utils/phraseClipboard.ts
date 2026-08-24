export interface ClipboardWriter {
  writeText: (content: string) => Promise<void>;
}


export async function copyPlainTextToClipboard(
  content: string,
  clipboard: ClipboardWriter | null | undefined = (
    typeof navigator === "undefined" ? undefined : navigator.clipboard
  ),
) {
  if (!clipboard?.writeText) return false;
  try {
    await clipboard.writeText(content);
    return true;
  } catch {
    return false;
  }
}
