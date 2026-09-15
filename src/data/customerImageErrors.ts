const imageErrors: Record<string, string> = {
  media_key_unavailable: "本地归档引用密钥不可用，请重新同步历史",
  image_decoder_unavailable: "缺少此图片格式的解码器，原文件仍保留",
  image_decode_limit: "图片像素或帧数超出安全限制",
  image_download_timeout: "原图下载超时，等待有限重试或手动同步",
  channel_login_required: "渠道登录失效，请先恢复连接",
  channel_verification_required: "平台要求人工验证，相关远程请求已停止",
  channel_access_required: "渠道访问需要恢复，相关远程请求已停止",
  channel_protection_skipped: "渠道保护中，图片尚未下载；完成人工验证后再同步",
  image_source_unavailable: "平台原图已不可获取，无法恢复该原图",
  image_too_large: "原图超过 25 MB 安全限制",
  image_file_missing: "本地原图文件缺失",
  image_invalid: "图片内容损坏或格式无效",
  image_not_archived: "图片尚未归档",
};

export function customerImageError(code?: string | null, message?: string | null) {
  return message || (code ? imageErrors[code] || `图片处理失败（${code}）` : "等待归档结果");
}
