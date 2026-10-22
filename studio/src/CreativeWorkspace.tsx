import { useEffect, useRef, useState } from 'react';
import type { Language } from './types';
import { toolUrl, workspaceTools } from './workspace';
import type { EmbeddedTool } from './workspace';

export function EmbeddedWorkspace({
  tool,
  language,
  active,
}: {
  tool: EmbeddedTool;
  language: Language;
  active: boolean;
}) {
  const info = workspaceTools.find((item) => item.id === tool)!;
  // 保持每个已访问页面的 iframe 实例，切换功能不会丢掉表单与上传草稿。
  const [frameLanguage, setFrameLanguage] = useState(language);
  const [attempt, setAttempt] = useState(0);
  const [ready, setReady] = useState(false);
  const [slow, setSlow] = useState(false);
  const [contentHeight, setContentHeight] = useState<number | undefined>();
  const frame = useRef<HTMLIFrameElement>(null);
  const lastNavigation = useRef(0);
  const activeRef = useRef(active);
  activeRef.current = active;
  const zh = language === 'zh-CN';
  const url = toolUrl(tool, frameLanguage);
  useEffect(() => {
    const origin = new URL(url).origin;
    const receive = (event: MessageEvent) => {
      if (event.origin !== origin || event.data?.tool !== tool) return;
      if (event.data?.type === 'frameweave:tool-ready') {
        setReady(true);
        setSlow(false);
      }
      // 高度通知只影响布局，不接收表单内容，也不接受任意来源的消息。
      if (
        event.data?.type === 'frameweave:tool-size' &&
        Number.isFinite(event.data.height) &&
        event.data.height >= 200 &&
        event.data.height <= 20000
      ) {
        setContentHeight(Math.ceil(event.data.height));
      }
      // 连续步骤在同一会话中切换；仅响应新的导航，普通编辑与高度变化不抢滚动。
      if (
        event.data?.type === 'frameweave:tool-step' &&
        Number.isSafeInteger(event.data.navigation) &&
        event.data.navigation > lastNavigation.current
      ) {
        lastNavigation.current = event.data.navigation;
        if (activeRef.current) {
          window.requestAnimationFrame(() => {
            frame.current?.scrollIntoView({ block: 'start', behavior: 'instant' });
          });
        }
      }
    };
    window.addEventListener('message', receive);
    const timer = window.setTimeout(() => setSlow(true), 18000);
    return () => {
      window.removeEventListener('message', receive);
      window.clearTimeout(timer);
    };
  }, [url, attempt, tool]);

  // 全局语言改变时保留当前输入；用户可明确选择重新加载这一页以同步语言。
  const refresh = () => {
    if (
      !window.confirm(
        zh
          ? '重新加载此功能会清除本页尚未保存的输入，是否继续？'
          : 'Reloading clears unsaved inputs in this tool. Continue?',
      )
    )
      return;
    setFrameLanguage(language);
    setReady(false);
    setSlow(false);
    setContentHeight(undefined);
    lastNavigation.current = 0;
    setAttempt((value) => value + 1);
  };
  return (
    <section className="embedded-workspace" hidden={!active} aria-label={zh ? info.zh : info.en}>
      <div className="embedded-heading">
        <div>
          <div className="eyebrow">
            {zh
              ? tool === 'settings' || tool === 'history'
                ? '工作空间管理'
                : '从一个想法开始'
              : tool === 'settings' || tool === 'history'
                ? 'YOUR WORKSPACE'
                : 'START WITH AN IDEA'}
          </div>
          <h1>{zh ? info.zh : info.en}</h1>
          <p>{zh ? info.hint : info.hintEn}</p>
        </div>
        <div className="embedded-actions">
          <span className={`tool-connection ${ready ? 'ready' : ''}`} role="status">
            {ready
              ? zh
                ? '页面已加载'
                : 'Page loaded'
              : zh
                ? '正在连接创作服务'
                : 'Connecting to creative service'}
          </span>
          <a className="text-link" href={url} target="_blank" rel="noreferrer">
            {zh ? '在新窗口打开' : 'Open in new window'} ↗
          </a>
        </div>
      </div>
      {frameLanguage !== language && (
        <div className="message warning">
          <span>
            {zh
              ? '此页保留了原语言和编辑内容，重新加载可同步工作台语言。'
              : 'This tool keeps its current language and draft. Reload to apply the workspace language.'}
          </span>
          <button onClick={refresh}>{zh ? '同步页面语言' : 'Apply language'}</button>
        </div>
      )}
      {slow && !ready && (
        <div className="message warning">
          <span>
            {zh
              ? '创作服务尚未就绪。请确认启动了完整工作台；也可以独立打开检查服务。'
              : 'The creative service is not ready. Check that the full workspace is running, or open the tool separately.'}
          </span>
          <button onClick={refresh}>{zh ? '重新连接' : 'Reconnect'}</button>
        </div>
      )}
      <iframe
        key={`${tool}-${attempt}`}
        ref={frame}
        title={zh ? info.zh : info.en}
        src={url}
        className="creative-tool-frame"
        style={contentHeight ? { height: contentHeight, minHeight: 0 } : undefined}
        allow="clipboard-write; microphone; camera; fullscreen"
      />
    </section>
  );
}
