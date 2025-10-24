export function generateTitleLocal(prompt: string, summary?: string): string {
  const base = (prompt || summary || "").trim();
  if (!base) return "New conversation";

  // Remove common polite prefixes / pronouns
  let s = base.replace(/^(please|can you|could you|would you|show|give me|tell me|me|my)\b[:,]?\s*/i, "");

  // Transform "compare X and Y" → "x vs y" (lowercase vs)
  const cmp = s.match(/compare\s+(.+?)\s+and\s+(.+)$/i);
  if (cmp) s = `${cmp[1]} vs ${cmp[2]}`;

  // Clean
  s = s.replace(/\s+/g, " ").replace(/[^\w\s()\-:./&]/g, "").trim();
  if (!s) return "New conversation";

  // Lowercase baseline, normalize vs, strip trailing punctuation
  s = s.toLowerCase();
  s = s.replace(/\bvs\b/gi, "vs");
  s = s.replace(/[\.;:!?]+$/g, "");

  // Sentence case (first letter uppercase only)
  s = s.charAt(0).toUpperCase() + s.slice(1);

  if (s.length > 60) s = s.slice(0, 60).trimEnd();
  return s;
}
