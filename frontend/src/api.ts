/** The server's refusal message from an error response, or the given fallback when it has none. */
export async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json() as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    // Fall through to the fallback message.
  }
  return `${fallback} (HTTP ${response.status}). Try again.`;
}
