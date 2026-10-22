export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// 错误只展示后端公开信息，不把请求头、密钥或私人文件路径写到控制台。
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: {
        ...(typeof options.body === 'string' ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new ApiError(0, '无法连接本地服务 / Cannot reach the local server');
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
      else if (typeof body.error === 'string') message = body.error;
      else if (Array.isArray(body.detail))
        message = body.detail.map((item: { msg?: string }) => item.msg).join('; ');
    } catch {
      /* 非 JSON 错误也保留 HTTP 状态，避免误报成功。 */
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export async function downloadProject(id: string, title: string) {
  const response = await fetch(`/api/projects/${encodeURIComponent(id)}/export`);
  if (!response.ok) throw new ApiError(response.status, '项目导出失败 / Project export failed');
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = `${title || 'FrameWeave'}.zip`;
  link.click();
  // 浏览器接管下载后再释放，避免较大文件尚未启动时失效。
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
