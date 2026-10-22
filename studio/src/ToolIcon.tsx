import type { WorkspaceView } from './workspace';

// 导航使用同一套描边图标，避免字符图标在不同中文字体下尺寸与基线不一致。
export function ToolIcon({ tool, size = 19 }: { tool: WorkspaceView; size?: number }) {
  const paths = {
    standard: (
      <>
        <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" />
        <path d="m20 2 .5 1.5L22 4l-1.5.5L20 6l-.5-1.5L18 4l1.5-.5Z" />
      </>
    ),
    digital_human: (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5 21v-2a7 7 0 0 1 14 0v2M3 7V3h4M17 3h4v4" />
      </>
    ),
    i2v: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="3" />
        <path d="m10 8 6 4-6 4Z" />
      </>
    ),
    asset_based: (
      <>
        <rect x="3" y="3" width="15" height="15" rx="3" />
        <path d="M7 21h11a3 3 0 0 0 3-3V7M3 14l5-5 4 4 3-3 3 3" />
        <circle cx="13" cy="7" r="1" />
      </>
    ),
    action_transfer: (
      <>
        <circle cx="15" cy="4" r="2" />
        <path d="m8 10 5-3 4 4 4 1M6 21l4-6 3-5M9 12l5 4 1 5M2 7h5M2 11h3" />
      </>
    ),
    history: (
      <>
        <path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v5l3 2" />
      </>
    ),
    settings: (
      <>
        <path d="M4 6h16M4 12h16M4 18h16" />
        <rect x="7" y="4" width="3" height="4" rx="1" fill="var(--surface)" />
        <rect x="14" y="10" width="3" height="4" rx="1" fill="var(--surface)" />
        <rect x="8" y="16" width="3" height="4" rx="1" fill="var(--surface)" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[tool]}
    </svg>
  );
}
