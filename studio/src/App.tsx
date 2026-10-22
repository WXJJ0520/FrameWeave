import { useEffect, useState } from 'react';
import { EmbeddedWorkspace } from './CreativeWorkspace';
import { readWorkspaceView, workspaceTools } from './workspace';
import type { WorkspaceView } from './workspace';
import type { Language } from './types';
import { ToolIcon } from './ToolIcon';

function BrandMark() {
  return (
    <svg width="33" height="33" viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="17" fill="currentColor" />
      <path d="M17 19h30v8H25v20h-8z" fill="#ffffff" />
      <path d="M31 33h16v14H31z" fill="#ffffff" />
      <path d="M31 27h8v6h-8z" fill="#b9a7ed" />
    </svg>
  );
}

export default function App() {
  const [view, setView] = useState<WorkspaceView>(readWorkspaceView);
  const [visitedTools, setVisitedTools] = useState<WorkspaceView[]>(() => [readWorkspaceView()]);
  const [language, setLanguage] = useState<Language>(() => {
    try {
      return localStorage.getItem('frameweave-language') === 'en' ? 'en' : 'zh-CN';
    } catch {
      return 'zh-CN';
    }
  });
  const zh = language === 'zh-CN';
  const current = workspaceTools.find((tool) => tool.id === view)!;

  useEffect(() => {
    const update = () => {
      const next = readWorkspaceView();
      // 旧书签和无效路由统一回到原有快速创作，不再挂载额外编辑器。
      if (window.location.hash !== `#${next}`) {
        window.history.replaceState(null, '', `#${next}`);
      }
      setView(next);
      setVisitedTools((previous) => (previous.includes(next) ? previous : [...previous, next]));
    };
    update();
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);

  useEffect(() => {
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    try {
      localStorage.setItem('frameweave-language', language);
    } catch {
      // 浏览器限制本地存储时，仍允许本次会话切换语言。
    }
  }, [language]);

  const navigate = (next: WorkspaceView) => {
    window.location.hash = next;
  };

  return (
    <div className="app-shell unified-workspace">
      <aside className="sidebar">
        <a className="brand" href="#standard" aria-label="镜织 FrameWeave">
          <BrandMark />
          <span>
            {zh ? '镜织' : 'FrameWeave'}
            <small>FRAMEWEAVE</small>
          </span>
        </a>
        <p className="sidebar-label">{zh ? '创作工具' : 'CREATIVE TOOLS'}</p>
        <nav className="workspace-nav" aria-label={zh ? '创作与管理' : 'Creation and settings'}>
          {workspaceTools.map((tool) => (
            <button
              key={tool.id}
              className={`workspace-nav-item ${view === tool.id ? 'active' : ''} ${tool.id === 'history' ? 'management-start' : ''}`}
              onClick={() => navigate(tool.id)}
              aria-current={view === tool.id ? 'page' : undefined}
            >
              <span className="nav-glyph" aria-hidden="true">
                <ToolIcon tool={tool.id} />
              </span>
              <span>{zh ? tool.zh : tool.en}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="local-dot" />
          {zh ? '本地运行' : 'Running locally'}
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span>{zh ? '工作空间' : 'Workspace'}</span>
            <span aria-hidden="true">/</span>
            <strong>{zh ? current.zh : current.en}</strong>
          </div>
          <div className="topbar-right">
            <button className="topbar-settings" onClick={() => navigate('settings')}>
              <ToolIcon tool="settings" size={16} />
              {zh ? '系统配置' : 'Settings'}
            </button>
            <div className="language-switch" role="group" aria-label={zh ? '界面语言' : 'Language'}>
              <button
                className={zh ? 'active' : ''}
                aria-pressed={zh}
                onClick={() => setLanguage('zh-CN')}
              >
                中文
              </button>
              <button
                className={!zh ? 'active' : ''}
                aria-pressed={!zh}
                onClick={() => setLanguage('en')}
              >
                EN
              </button>
            </div>
          </div>
        </header>
        <main className="tool-main">
          {/* 保持原流程页面实例，切换功能不清除尚未提交的文案和素材。 */}
          {visitedTools.map((tool) => (
            <EmbeddedWorkspace key={tool} tool={tool} language={language} active={view === tool} />
          ))}
        </main>
        <footer className="app-footer">
          <span>镜织 · FrameWeave</span>
          <span>
            Built on{' '}
            <a href="https://github.com/ATH-MaaS/Pixelle-Video" target="_blank" rel="noreferrer">
              Pixelle-Video
            </a>
          </span>
        </footer>
      </div>
    </div>
  );
}
