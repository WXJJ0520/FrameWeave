// 导航只包含原有创作与管理能力，排版优化不扩展产品功能范围。
export const workspaceTools = [
  {
    id: 'standard',
    zh: '快速创作',
    en: 'Quick create',
    hint: '从想法、脚本到配音与成片',
    hintEn: 'From an idea to a narrated video',
    glyph: '✦',
  },
  {
    id: 'digital_human',
    zh: '数字人口播',
    en: 'Digital presenter',
    hint: '人物素材、口播音频与数字人 API',
    hintEn: 'Presenter footage, speech, and avatar APIs',
    glyph: '◉',
  },
  {
    id: 'i2v',
    zh: '图生视频',
    en: 'Image to video',
    hint: '用参考图片生成动态视频',
    hintEn: 'Turn reference images into moving scenes',
    glyph: '▷',
  },
  {
    id: 'asset_based',
    zh: '自定义素材',
    en: 'Custom footage',
    hint: '用自己的图片、视频和素材创作',
    hintEn: 'Create with your own pictures and footage',
    glyph: '▧',
  },
  {
    id: 'action_transfer',
    zh: '动作迁移',
    en: 'Motion transfer',
    hint: '角色图片、参考动作与视频 API',
    hintEn: 'Character images, reference motion, and video APIs',
    glyph: '⌁',
  },
  {
    id: 'history',
    zh: '作品记录',
    en: 'Creation history',
    hint: '查看原有生成记录与成品',
    hintEn: 'Browse your existing generations and outputs',
    glyph: '◷',
  },
  {
    id: 'settings',
    zh: '系统配置',
    en: 'System settings',
    hint: '模型、API 密钥、服务地址与连接测试',
    hintEn: 'Models, API keys, service URLs, and connection tests',
    glyph: '⚙',
  },
] as const;

export type WorkspaceView = (typeof workspaceTools)[number]['id'];
export type EmbeddedTool = WorkspaceView;

export function readWorkspaceView(): WorkspaceView {
  const id = window.location.hash.slice(1);
  return workspaceTools.some((tool) => tool.id === id) ? (id as WorkspaceView) : 'standard';
}

export function toolUrl(tool: EmbeddedTool, language: string): string {
  // 仅指向同一台机器的创作服务，不从查询参数接收任意第三方 URL。
  const target = new URL(window.location.origin);
  target.port = '8501';
  target.pathname = '/';
  target.hash = '';
  target.search = new URLSearchParams({
    embed: 'true',
    frameweave: '1',
    tool,
    language: language === 'en' ? 'en_US' : 'zh_CN',
    parent_origin: window.location.origin,
  }).toString();
  return target.toString();
}
