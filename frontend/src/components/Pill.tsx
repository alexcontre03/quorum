interface PillProps {
  text: string;
  variant?: string;
}

export function Pill({ text, variant = "subtle" }: PillProps) {
  return <span className={`pill ${variant}`}>{text}</span>;
}
