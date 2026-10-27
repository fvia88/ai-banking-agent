import type { SVGProps } from 'react';

const paths = {
  chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z M7 9h10M7 13h6',
  wallet: 'M20 8V5a2 2 0 0 0-2-2H5a3 3 0 0 0 0 6h15v11H5a3 3 0 0 1-3-3V6 M20 12h-5v4h5',
  activity: 'M3 3v18h18M6 14l4-4 4 3 6-8',
  repeat: 'm17 2 4 4-4 4M3 11V8a2 2 0 0 1 2-2h16M7 22l-4-4 4-4m14-1v3a2 2 0 0 1-2 2H3',
  shield: 'm12 2 8 3v6c0 5-8 10-8 10S4 16 4 11V5l8-3Zm-4 9 3 3 5-6',
  arrow: 'M7 17 17 7M7 7h10v10',
  refresh: 'M20 7a8 8 0 1 0 1 8M20 2v5h-5',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'm6 6 12 12M6 18 18 6',
  send: 'M12 19V5m-6 6 6-6 6 6',
  lock: 'M6 10h12v11H6V10Zm2 0V6a4 4 0 0 1 8 0v4',
  check: 'm5 12 4 4L19 6',
} as const;

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: keyof typeof paths }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}><path d={paths[name]} /></svg>;
}
