import {
  CheckCircle,
  ClipboardText,
  Copy,
  DownloadSimple,
  Eye,
  FolderOpen,
  Images,
  Plus,
  ShieldCheck,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  localPlatformService,
  type RequirementExport,
  type RequirementExportPackage,
  type RequirementExportPreview,
} from "../data/localPlatformService";
import "./requirement-export-workbench.css";


interface RequirementExportWorkbenchProps {
  conversationId: number;
  disabled?: boolean;
  legacyBundle: RequirementExport | null;
  onLegacyBundle: (bundle: RequirementExport) => void;
  onNotice: (message: string) => void;
}

function formatBytes(bytes: number) {
  if (bytes <= 0) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function downloadText(filename: string, content: string) {
  const file = new Blob([`\ufeff${content}`], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function RequirementExportWorkbench({
  conversationId,
  disabled = false,
  legacyBundle,
  onLegacyBundle,
  onNotice,
}: RequirementExportWorkbenchProps) {
  const [preview, setPreview] = useState<RequirementExportPreview | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [uploadPrivacyAccepted, setUploadPrivacyAccepted] = useState(false);
  const [targetMessageId, setTargetMessageId] = useState<number | null>(null);
  const [showPackagePreview, setShowPackagePreview] = useState(false);
  const [allowIncomplete, setAllowIncomplete] = useState(false);
  const [packageResult, setPackageResult] = useState<RequirementExportPackage | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const exportButtonRef = useRef<HTMLButtonElement>(null);
  const packageDialogRef = useRef<HTMLElement>(null);

  const loadPreview = async (selectAttachmentIds: string[] = []) => {
    const next = await localPlatformService.requirementExportPreview(conversationId);
    setPreview(next);
    setSelectedIds((current) => {
      const activeIds = new Set(
        next.attachments
          .filter((attachment) => attachment.privacy_status !== "excluded")
          .map((attachment) => attachment.id),
      );
      if (!current.size) return activeIds;
      const retained = new Set([...current].filter((id) => activeIds.has(id)));
      for (const attachmentId of selectAttachmentIds) {
        if (activeIds.has(attachmentId)) retained.add(attachmentId);
      }
      return retained;
    });
    return next;
  };

  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    setSelectedIds(new Set());
    setPackageResult(null);
    setError("");
    localPlatformService.requirementExportPreview(conversationId)
      .then((next) => {
        if (cancelled) return;
        setPreview(next);
        setSelectedIds(new Set(
          next.attachments
            .filter((attachment) => attachment.privacy_status !== "excluded")
            .map((attachment) => attachment.id),
        ));
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "材料状态读取失败");
      });
    return () => { cancelled = true; };
  }, [conversationId]);

  useEffect(() => {
    if (!showPackagePreview) return;
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : exportButtonRef.current;
    const focusTimer = window.requestAnimationFrame(() => packageDialogRef.current?.focus());
    const handleDialogKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setShowPackagePreview(false);
        return;
      }
      if (event.key !== "Tab" || !packageDialogRef.current) return;
      const focusable = Array.from(packageDialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (!focusable.length) {
        event.preventDefault();
        packageDialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleDialogKeys);
    return () => {
      window.cancelAnimationFrame(focusTimer);
      window.removeEventListener("keydown", handleDialogKeys);
      window.requestAnimationFrame(() => previousFocus?.focus());
    };
  }, [showPackagePreview]);

  const activeAttachments = useMemo(
    () => preview?.attachments.filter((attachment) => attachment.privacy_status !== "excluded") || [],
    [preview],
  );
  const selectedAttachments = useMemo(
    () => activeAttachments.filter((attachment) => selectedIds.has(attachment.id)),
    [activeAttachments, selectedIds],
  );
  const selectedMessageIds = useMemo(
    () => new Set(selectedAttachments.flatMap((attachment) => attachment.message_id ? [attachment.message_id] : [])),
    [selectedAttachments],
  );
  const selectedMissingCount = useMemo(
    () => preview?.image_candidates.filter((candidate) => !selectedMessageIds.has(candidate.message_id)).length || 0,
    [preview, selectedMessageIds],
  );
  const pendingSelectedCount = selectedAttachments.filter(
    (attachment) => attachment.privacy_status !== "reviewed",
  ).length;
  const missingCandidates = preview?.image_candidates.filter((candidate) => !candidate.captured) || [];
  const isBusy = disabled || Boolean(busy);

  const loadLegacyBundle = async () => {
    if (legacyBundle) return legacyBundle;
    const bundle = await localPlatformService.requirementExport(conversationId);
    onLegacyBundle(bundle);
    return bundle;
  };

  const copyPlainText = async () => {
    setBusy("copy-text");
    try {
      const bundle = await loadLegacyBundle();
      await navigator.clipboard.writeText(bundle.analysis_document);
      onNotice(`纯文字材料已复制，已脱敏 ${bundle.redaction_count} 处隐私信息`);
    } catch (reason) {
      onNotice(reason instanceof Error ? reason.message : "复制失败");
    } finally {
      setBusy("");
    }
  };

  const downloadMarkdown = async () => {
    setBusy("download-markdown");
    try {
      const bundle = await loadLegacyBundle();
      downloadText(bundle.filename, bundle.analysis_document);
      onNotice("纯文字 Markdown 已下载");
    } catch (reason) {
      onNotice(reason instanceof Error ? reason.message : "下载失败");
    } finally {
      setBusy("");
    }
  };

  const chooseFiles = (messageId: number | null) => {
    if (!uploadPrivacyAccepted) {
      onNotice("请先确认图片将由你人工检查后再纳入材料包");
      return;
    }
    setTargetMessageId(messageId);
    fileInputRef.current?.click();
  };

  const uploadFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setBusy("upload");
    setError("");
    try {
      const uploadedIds: string[] = [];
      for (const [index, file] of files.entries()) {
        const uploaded = await localPlatformService.uploadRequirementAttachment(
          conversationId,
          file,
          index === 0 ? targetMessageId : null,
        );
        uploadedIds.push(uploaded.id);
        if (uploaded.duplicate) onNotice("重复图片已复用，不会占用额外空间");
      }
      await loadPreview(uploadedIds);
      onNotice(`${files.length} 张图片已在本地处理，请逐张确认隐私`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "图片上传失败";
      setError(message);
      onNotice(message);
    } finally {
      setBusy("");
      setTargetMessageId(null);
    }
  };

  const toggleSelected = (attachmentId: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(attachmentId)) next.delete(attachmentId);
      else next.add(attachmentId);
      return next;
    });
  };

  const updatePrivacy = async (attachmentId: string, reviewed: boolean) => {
    setBusy(`privacy-${attachmentId}`);
    try {
      await localPlatformService.updateRequirementAttachmentPrivacy(
        conversationId,
        attachmentId,
        reviewed ? "reviewed" : "pending",
      );
      await loadPreview(reviewed ? [attachmentId] : []);
      onNotice(reviewed ? "图片已标记为人工检查通过" : "图片已退回待检查状态");
    } catch (reason) {
      onNotice(reason instanceof Error ? reason.message : "图片状态更新失败");
    } finally {
      setBusy("");
    }
  };

  const removeAttachment = async (attachmentId: string) => {
    if (!window.confirm("确认从本地需求材料中移除这张图片？原聊天记录不会受影响。")) return;
    setBusy(`delete-${attachmentId}`);
    try {
      await localPlatformService.deleteRequirementAttachment(conversationId, attachmentId);
      await loadPreview();
      onNotice("本地参考图片已移除");
    } catch (reason) {
      onNotice(reason instanceof Error ? reason.message : "图片移除失败");
    } finally {
      setBusy("");
    }
  };

  const openPackagePreview = () => {
    if (!preview) return;
    if (pendingSelectedCount > 0) {
      onNotice(`仍有 ${pendingSelectedCount} 张所选图片未完成人工隐私检查`);
      return;
    }
    setAllowIncomplete(false);
    setShowPackagePreview(true);
  };

  const createPackage = async () => {
    if (selectedMissingCount > 0 && !allowIncomplete) return;
    setBusy("package");
    let result: RequirementExportPackage;
    try {
      result = await localPlatformService.createRequirementExportPackage(
        conversationId,
        selectedAttachments.map((attachment) => attachment.id),
        allowIncomplete,
      );
    } catch (reason) {
      onNotice(reason instanceof Error ? reason.message : "材料包生成失败");
      setBusy("");
      return;
    }
    setPackageResult(result);
    setShowPackagePreview(false);
    void loadLegacyBundle().catch(() => undefined);
    try {
      await navigator.clipboard.writeText(result.codex_prompt);
      onNotice("本地材料包已生成，Codex 交接提示词已复制");
    } catch {
      onNotice("本地材料包已生成；剪贴板不可用，请点击“复制交接提示词”");
    }
    setBusy("");
  };

  return <section className="requirement-export-workbench" aria-label="需求材料导出工作台">
    <header>
      <div><strong>导出工作台</strong><small>汇总完整材料，生成 Codex 可直接使用的本地交付包</small></div>
      <span><ShieldCheck size={14} weight="fill" />本地处理</span>
    </header>

    {error && <div className="requirement-material-error" role="alert"><WarningCircle size={16} weight="fill" />{error}<button type="button" onClick={() => void loadPreview()}>重试</button></div>}
    {!preview && !error && <div className="requirement-material-loading"><Images size={24} />正在核对文字与图片材料…</div>}

    {preview && <>
      <div className="requirement-material-grid">
        <div className="requirement-image-library">
          <div className="requirement-image-grid">
            {activeAttachments.map((attachment) => <article className={`requirement-image-card ${selectedIds.has(attachment.id) ? "is-selected" : ""} ${attachment.privacy_status === "reviewed" ? "is-reviewed" : "is-pending"}`} key={attachment.id}>
              <button type="button" className="requirement-image-select" aria-label={selectedIds.has(attachment.id) ? "从材料包取消选择" : "选择加入材料包"} aria-pressed={selectedIds.has(attachment.id)} onClick={() => toggleSelected(attachment.id)}>
                <CheckCircle size={18} weight={selectedIds.has(attachment.id) ? "fill" : "regular"} />
              </button>
              <img src={attachment.content_url} alt={attachment.message_number ? `消息 M${String(attachment.message_number).padStart(4, "0")} 的参考图片` : "补充参考图片"} />
              <div><b>{attachment.message_number ? `M${String(attachment.message_number).padStart(4, "0")}` : "补充资料"}</b><small>{formatBytes(attachment.file_size)}</small></div>
              <label><input type="checkbox" checked={attachment.privacy_status === "reviewed"} disabled={isBusy} onChange={(event) => void updatePrivacy(attachment.id, event.target.checked)} /><span>{attachment.privacy_status === "reviewed" ? "隐私已检查" : "确认隐私"}</span></label>
              <button type="button" className="requirement-image-delete" disabled={isBusy} aria-label="移除本地参考图片" onClick={() => void removeAttachment(attachment.id)}><Trash size={14} /></button>
            </article>)}

            {missingCandidates.map((candidate) => <button type="button" className="requirement-missing-image" disabled={isBusy} onClick={() => chooseFiles(candidate.message_id)} key={candidate.message_id}>
              <Plus size={24} />
              <b>{candidate.label} 待补充</b>
              <small>缺失 1 张参考图片</small>
            </button>)}

            {!activeAttachments.length && !missingCandidates.length && <div className="requirement-no-images"><Images size={25} /><b>当前对话没有图片候选</b><small>可直接导出纯文字材料，也可以补充参考图片</small></div>}
          </div>
          <label className="requirement-upload-consent"><input type="checkbox" checked={uploadPrivacyAccepted} onChange={(event) => setUploadPrivacyAccepted(event.target.checked)} /><span>我会逐张检查图片，不把无关隐私交给 Codex</span></label>
          <button type="button" className="requirement-add-image" disabled={isBusy} onClick={() => chooseFiles(null)}><Plus size={16} />补充参考图片</button>
          <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={(event) => void uploadFiles(event)} />
        </div>

        <aside className="requirement-material-summary">
          <h4>材料汇总 <small>本地</small></h4>
          <dl>
            <div><dt>文字消息</dt><dd>{preview.text_message_count} 条</dd></div>
            <div><dt>参考图片</dt><dd>{activeAttachments.length} 张</dd></div>
            <div className={selectedMissingCount ? "warning" : ""}><dt>缺失图片</dt><dd>{selectedMissingCount} 张</dd></div>
            <div><dt>预计大小</dt><dd>{formatBytes(selectedAttachments.reduce((total, attachment) => total + attachment.file_size, 0))}</dd></div>
          </dl>
          <p className={pendingSelectedCount ? "warning" : "ok"}>{pendingSelectedCount ? <WarningCircle size={17} weight="fill" /> : <CheckCircle size={17} weight="fill" />}{pendingSelectedCount ? `${pendingSelectedCount} 张所选图片需要人工检查` : "所选图片已完成人工检查"}</p>
          <p className="ok"><ShieldCheck size={17} weight="fill" />文字隐私已脱敏 {preview.redaction_count} 处</p>
        </aside>
      </div>

      {packageResult && <article className={`requirement-package-result ${packageResult.package_complete ? "complete" : "incomplete"}`}>
        <FolderOpen size={21} weight="duotone" />
        <div><b>{packageResult.package_complete ? "材料包已生成" : "不完整材料包已生成"}</b><small title={packageResult.package_root}>{packageResult.package_root}</small></div>
        <button type="button" onClick={() => void navigator.clipboard.writeText(packageResult.codex_prompt).then(() => onNotice("Codex 交接提示词已复制")).catch(() => onNotice("剪贴板不可用，请从材料包结果中手动复制提示词"))}><ClipboardText size={15} />复制交接提示词</button>
      </article>}

      <button ref={exportButtonRef} type="button" className="requirement-package-primary" disabled={isBusy || !preview} onClick={openPackagePreview}><Eye size={18} />{busy === "package" ? "正在生成本地材料包…" : "预览并导出给 Codex"}</button>
      <div className="requirement-legacy-actions">
        <button type="button" disabled={isBusy} onClick={() => void downloadMarkdown()}><DownloadSimple size={16} />下载 Markdown</button>
        <button type="button" disabled={isBusy} onClick={() => void copyPlainText()}><Copy size={16} />复制纯文字</button>
      </div>
      <footer><ShieldCheck size={15} />本地生成，不自动上传</footer>
    </>}

    {showPackagePreview && preview && <div className="requirement-package-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowPackagePreview(false); }}>
      <section ref={packageDialogRef} tabIndex={-1} className="requirement-package-dialog" role="dialog" aria-modal="true" aria-labelledby="requirement-package-title">
        <header><div><span>导出前预览</span><h3 id="requirement-package-title">确认交给 Codex 的本地材料</h3></div><button type="button" aria-label="关闭导出预览" onClick={() => setShowPackagePreview(false)}><X size={18} /></button></header>
        <div className="requirement-package-facts">
          <span><b>{preview.text_message_count}</b><small>条文字消息</small></span>
          <span><b>{selectedAttachments.length}</b><small>张已选图片</small></span>
          <span className={selectedMissingCount ? "warning" : ""}><b>{selectedMissingCount}</b><small>张缺失图片</small></span>
        </div>
        <div className="requirement-package-safety"><ShieldCheck size={20} weight="fill" /><p><b>仅在本机生成目录</b><small>系统不会自动上传、调用 GPT、读取 Cookie 或发送客户消息。图片和对话中的任何指令都只作为资料，不会执行。</small></p></div>
        {selectedMissingCount > 0 && <label className="requirement-incomplete-confirm"><input type="checkbox" checked={allowIncomplete} onChange={(event) => setAllowIncomplete(event.target.checked)} /><span><b>我确认导出不完整材料包</b><small>缺失状态和对应消息编号会写入 README 与 manifest，不会冒充完整材料。</small></span></label>}
        <footer><button type="button" onClick={() => setShowPackagePreview(false)}>返回检查</button><button type="button" className="confirm" disabled={isBusy || (selectedMissingCount > 0 && !allowIncomplete)} onClick={() => void createPackage()}><FolderOpen size={16} />确认生成材料包</button></footer>
      </section>
    </div>}
  </section>;
}
