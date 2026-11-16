import type { Transition, Variants } from "framer-motion";

export const spring: Transition = { type: "spring", stiffness: 320, damping: 30, mass: 0.8 };
export const softSpring: Transition = { type: "spring", stiffness: 220, damping: 26 };

export const pageVariants: Variants = {
  initial: { opacity: 0, y: 14, filter: "blur(4px)" },
  enter: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.34, ease: [0.22, 1, 0.36, 1] } },
  exit: { opacity: 0, y: -8, filter: "blur(3px)", transition: { duration: 0.18, ease: [0.4, 0, 1, 1] } },
};

export const stagger: Variants = {
  initial: {},
  enter: { transition: { staggerChildren: 0.055, delayChildren: 0.04 } },
};

export const riseItem: Variants = {
  initial: { opacity: 0, y: 12 },
  enter: { opacity: 1, y: 0, transition: { duration: 0.36, ease: [0.22, 1, 0.36, 1] } },
};

export const scaleIn: Variants = {
  initial: { opacity: 0, scale: 0.96 },
  enter: { opacity: 1, scale: 1, transition: spring },
  exit: { opacity: 0, scale: 0.97, transition: { duration: 0.14 } },
};

export const slideStep: Variants = {
  initial: (dir: number) => ({ opacity: 0, x: dir > 0 ? 42 : -42 }),
  enter: { opacity: 1, x: 0, transition: { duration: 0.38, ease: [0.22, 1, 0.36, 1] } },
  exit: (dir: number) => ({ opacity: 0, x: dir > 0 ? -42 : 42, transition: { duration: 0.22 } }),
};
