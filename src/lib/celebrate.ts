export async function celebrate(tone: "session" | "finish" | "onboard" = "session") {
  try {
    const confetti = (await import("canvas-confetti")).default;
    const colors =
      tone === "onboard" ? ["#ff7a45", "#8b7bff", "#4abe8a", "#e8dfcf"] : ["#ff7a45", "#8b7bff", "#4abe8a"];
    const base = { colors, disableForReducedMotion: true, zIndex: 90 };
    if (tone === "finish") {
      confetti({ ...base, particleCount: 120, spread: 75, origin: { y: 0.62 } });
      setTimeout(() => confetti({ ...base, particleCount: 70, spread: 110, origin: { y: 0.5 } }), 180);
      return;
    }
    confetti({ ...base, particleCount: tone === "onboard" ? 90 : 45, spread: 60, origin: { y: 0.7 } });
  } catch {
    /* confetti is a nicety, never a failure */
  }
}
