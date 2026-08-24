import {
  ArrowCounterClockwise,
  ArrowDown,
  ArrowUp,
  CheckCircle,
  ClipboardText,
  Copy,
  PencilSimple,
  Plus,
  Prohibit,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  type FormEvent,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  localPlatformService,
  type PhraseLibraryView,
  type PhraseSnippetView,
} from "../data/localPlatformService";
import { copyPlainTextToClipboard } from "../utils/phraseClipboard";
import "./phrase-library-drawer.css";


function mutationId(prefix: string) {
  const value = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${value.replace(/-/g, "_")}`;
}

type Feedback = { kind: "success" | "error"; message: string } | null;

export function PhraseLibraryDrawer({
  open,
  onClose,
  triggerRef,
}: {
  open: boolean;
  onClose: () => void;
  triggerRef: RefObject<HTMLButtonElement | null>;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const feedbackTimerRef = useRef<number | null>(null);
  const [library, setLibrary] = useState<PhraseLibraryView | null>(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showInactive, setShowInactive] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [phraseFormOpen, setPhraseFormOpen] = useState(false);
  const [editingPhraseId, setEditingPhraseId] = useState<string | null>(null);
  const [phraseCategoryId, setPhraseCategoryId] = useState("");
  const [phraseContent, setPhraseContent] = useState("");
  const [categoryFormOpen, setCategoryFormOpen] = useState(false);
  const [categoryName, setCategoryName] = useState("");

  const notify = (next: NonNullable<Feedback>) => {
    setFeedback(next);
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
    feedbackTimerRef.current = window.setTimeout(() => setFeedback(null), 3200);
  };

  const applyLibrary = (next: PhraseLibraryView) => {
    setLibrary(next);
    setSelectedCategoryId((current) => next.categories.some((row) => row.id === current)
      ? current
      : next.categories[0]?.id || "");
  };

  const load = async () => {
    setLoading(true);
    try {
      applyLibrary(await localPlatformService.phraseLibrary());
    } catch (reason) {
      notify({ kind: "error", message: reason instanceof Error ? reason.message : "话术库加载失败" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    document.body.classList.add("phrase-library-open");
    const focusTimer = window.setTimeout(() => closeRef.current?.focus(), 60);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const drawer = drawerRef.current;
      if (!drawer) return;
      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(
        'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.offsetParent !== null);
      if (!focusable.length) return;
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
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("phrase-library-open");
      triggerRef.current?.focus();
    };
  }, [open, onClose, triggerRef]);

  useEffect(() => () => {
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
  }, []);

  const selectedCategory = library?.categories.find((row) => row.id === selectedCategoryId) || null;
  const visiblePhrases = useMemo(() => {
    if (!selectedCategory) return [];
    return selectedCategory.phrases.filter((row) => showInactive || row.active);
  }, [selectedCategory, showInactive]);
  const activePhrases = useMemo(
    () => selectedCategory?.phrases.filter((row) => row.active) || [],
    [selectedCategory],
  );

  const refreshAfterFailure = async (reason: unknown, fallback: string) => {
    notify({ kind: "error", message: reason instanceof Error ? reason.message : fallback });
    try {
      applyLibrary(await localPlatformService.phraseLibrary());
    } catch {
      // Keep the original actionable error visible.
    }
  };

  const openNewPhrase = () => {
    if (!selectedCategory) return;
    setEditingPhraseId(null);
    setPhraseCategoryId(selectedCategory.id);
    setPhraseContent("");
    setPhraseFormOpen(true);
  };

  const openEditPhrase = (phrase: PhraseSnippetView) => {
    setEditingPhraseId(phrase.id);
    setPhraseCategoryId(phrase.category_id);
    setPhraseContent(phrase.content);
    setPhraseFormOpen(true);
  };

  const savePhrase = async (event: FormEvent) => {
    event.preventDefault();
    if (!library || !phraseContent.trim() || !phraseCategoryId) return;
    setBusy(true);
    try {
      const next = editingPhraseId
        ? await localPlatformService.updatePhrase(editingPhraseId, {
          request_id: mutationId("phrase_update"),
          expected_revision: library.revision,
          category_id: phraseCategoryId,
          content: phraseContent,
        })
        : await localPlatformService.createPhrase({
          request_id: mutationId("phrase_create"),
          expected_revision: library.revision,
          category_id: phraseCategoryId,
          content: phraseContent,
        });
      applyLibrary(next);
      setSelectedCategoryId(phraseCategoryId);
      setPhraseFormOpen(false);
      setEditingPhraseId(null);
      setPhraseContent("");
      notify({ kind: "success", message: editingPhraseId ? "话术已更新" : "话术已保存" });
    } catch (reason) {
      await refreshAfterFailure(reason, "话术保存失败");
    } finally {
      setBusy(false);
    }
  };

  const saveCategory = async (event: FormEvent) => {
    event.preventDefault();
    if (!library || !categoryName.trim()) return;
    setBusy(true);
    try {
      const next = await localPlatformService.createPhraseCategory({
        request_id: mutationId("phrase_category"),
        expected_revision: library.revision,
        name: categoryName,
      });
      const added = next.categories.find((row) => !library.categories.some((old) => old.id === row.id));
      applyLibrary(next);
      if (added) setSelectedCategoryId(added.id);
      setCategoryName("");
      setCategoryFormOpen(false);
      notify({ kind: "success", message: "自定义分类已新增" });
    } catch (reason) {
      await refreshAfterFailure(reason, "分类新增失败");
    } finally {
      setBusy(false);
    }
  };

  const setActivation = async (phrase: PhraseSnippetView, active: boolean) => {
    if (!library) return;
    setBusy(true);
    try {
      applyLibrary(await localPlatformService.setPhraseActivation(phrase.id, {
        request_id: mutationId("phrase_activation"),
        expected_revision: library.revision,
        active,
      }));
      notify({ kind: "success", message: active ? "话术已恢复" : "话术已停用，原记录仍保留" });
    } catch (reason) {
      await refreshAfterFailure(reason, active ? "话术恢复失败" : "话术停用失败");
    } finally {
      setBusy(false);
    }
  };

  const movePhrase = async (phraseId: string, direction: -1 | 1) => {
    if (!library || !selectedCategory) return;
    const currentIndex = activePhrases.findIndex((row) => row.id === phraseId);
    const targetIndex = currentIndex + direction;
    if (currentIndex < 0 || targetIndex < 0 || targetIndex >= activePhrases.length) return;
    const phraseIds = activePhrases.map((row) => row.id);
    [phraseIds[currentIndex], phraseIds[targetIndex]] = [phraseIds[targetIndex], phraseIds[currentIndex]];
    setBusy(true);
    try {
      applyLibrary(await localPlatformService.reorderPhrases({
        request_id: mutationId("phrase_reorder"),
        expected_revision: library.revision,
        category_id: selectedCategory.id,
        phrase_ids: phraseIds,
      }));
      notify({ kind: "success", message: "话术顺序已更新" });
    } catch (reason) {
      await refreshAfterFailure(reason, "话术排序失败");
    } finally {
      setBusy(false);
    }
  };

  const copyPhrase = async (content: string) => {
    if (await copyPlainTextToClipboard(content)) {
      notify({ kind: "success", message: "已复制，不会自动发送" });
    } else {
      notify({ kind: "error", message: "复制失败，请手动选择文本" });
    }
  };

  if (!open) return null;

  return createPortal(<div className="phrase-library-layer">
    <button type="button" className="phrase-library-backdrop" aria-label="关闭话术库" onClick={onClose} />
    <aside ref={drawerRef} className="phrase-library-drawer" role="dialog" aria-modal="true" aria-labelledby="phrase-library-title">
      <span className="phrase-library-sheet-handle" aria-hidden="true" />
      <header className="phrase-library-heading">
        <span><small>MANUAL PHRASE CLIPBOARD</small><h2 id="phrase-library-title">话术库</h2><p><ClipboardText size={14} />只复制，不会自动发送</p></span>
        <button ref={closeRef} type="button" aria-label="关闭话术库" onClick={onClose}><X size={20} /></button>
      </header>

      {loading && !library
        ? <div className="phrase-library-loading">正在读取本地话术库…</div>
        : library && <>
          <nav className="phrase-category-tabs" aria-label="话术分类">
            {library.categories.map((category) => <button
              type="button"
              className={category.id === selectedCategoryId ? "active" : ""}
              aria-current={category.id === selectedCategoryId ? "true" : undefined}
              onClick={() => {
                setSelectedCategoryId(category.id);
                setPhraseFormOpen(false);
              }}
              key={category.id}
            >{category.name}</button>)}
            <button type="button" className="phrase-category-add" onClick={() => setCategoryFormOpen((value) => !value)}><Plus size={14} />自定义分类</button>
          </nav>

          {categoryFormOpen && <form className="phrase-inline-form phrase-category-form" onSubmit={(event) => void saveCategory(event)}>
            <label htmlFor="phrase-category-name">分类名称</label>
            <div><input id="phrase-category-name" value={categoryName} maxLength={32} autoFocus onChange={(event) => setCategoryName(event.target.value)} placeholder="例如：需求澄清" /><button type="submit" disabled={busy || !categoryName.trim()}>新增</button><button type="button" onClick={() => setCategoryFormOpen(false)}>取消</button></div>
          </form>}

          <section className="phrase-library-toolbar">
            <span><b>{selectedCategory?.name || "话术"}</b><small>{activePhrases.length} 条启用话术</small></span>
            <div>
              <button type="button" className={showInactive ? "active" : ""} onClick={() => setShowInactive((value) => !value)}>{showInactive ? "隐藏停用" : "查看停用"}</button>
              <button type="button" className="primary" onClick={openNewPhrase} disabled={!selectedCategory}><Plus size={16} />新增话术</button>
            </div>
          </section>

          {phraseFormOpen && <form className="phrase-inline-form phrase-editor" onSubmit={(event) => void savePhrase(event)}>
            <header><b>{editingPhraseId ? "编辑话术" : "新增话术"}</b><small>纯文本 · 不支持变量或自动发送</small></header>
            <label htmlFor="phrase-category-select">所属分类</label>
            <select id="phrase-category-select" value={phraseCategoryId} onChange={(event) => setPhraseCategoryId(event.target.value)}>
              {library.categories.map((category) => <option value={category.id} key={category.id}>{category.name}</option>)}
            </select>
            <label htmlFor="phrase-content">话术内容</label>
            <textarea id="phrase-content" value={phraseContent} maxLength={4000} autoFocus onChange={(event) => setPhraseContent(event.target.value)} placeholder="输入需要重复使用的固定话术" />
            <footer><small>{phraseContent.length}/4000</small><button type="button" onClick={() => setPhraseFormOpen(false)}>取消</button><button type="submit" className="primary" disabled={busy || !phraseContent.trim()}>保存话术</button></footer>
          </form>}

          {!phraseFormOpen && <div className="phrase-list" aria-busy={busy}>
            {visiblePhrases.length === 0
              ? <div className="phrase-empty"><span><ClipboardText size={28} weight="duotone" /></span><b>{showInactive ? "当前分类没有停用话术" : "当前分类暂无话术"}</b><p>这里不会自动生成内容，请由你手工添加真实话术。</p><button type="button" onClick={openNewPhrase}><Plus size={16} />新增第一条话术</button></div>
              : visiblePhrases.map((phrase) => {
                const activeIndex = activePhrases.findIndex((row) => row.id === phrase.id);
                return <article className={`phrase-card${phrase.active ? "" : " inactive"}`} key={phrase.id}>
                  <p tabIndex={0}>{phrase.content}</p>
                  <footer>
                    {phrase.active && <button type="button" className="copy" onClick={() => void copyPhrase(phrase.content)}><Copy size={16} />复制</button>}
                    <button type="button" onClick={() => openEditPhrase(phrase)}><PencilSimple size={16} />编辑</button>
                    {phrase.active && <>
                      <button type="button" aria-label="上移话术" title="上移" disabled={busy || activeIndex <= 0} onClick={() => void movePhrase(phrase.id, -1)}><ArrowUp size={16} /></button>
                      <button type="button" aria-label="下移话术" title="下移" disabled={busy || activeIndex < 0 || activeIndex >= activePhrases.length - 1} onClick={() => void movePhrase(phrase.id, 1)}><ArrowDown size={16} /></button>
                    </>}
                    <button type="button" className="activation" disabled={busy} onClick={() => void setActivation(phrase, !phrase.active)}>{phrase.active ? <><Prohibit size={16} />停用</> : <><ArrowCounterClockwise size={16} />恢复</>}</button>
                  </footer>
                </article>;
              })}
          </div>}
        </>}

      <footer className="phrase-library-boundary"><WarningCircle size={16} /><span>复制后请自行检查并粘贴到闲鱼或微信；本页面不会打开平台，也不会发送消息。</span></footer>
      {feedback && <div className={`phrase-library-feedback ${feedback.kind}`} role={feedback.kind === "error" ? "alert" : "status"}>{feedback.kind === "success" ? <CheckCircle size={17} weight="fill" /> : <WarningCircle size={17} weight="fill" />}{feedback.message}</div>}
    </aside>
  </div>, document.body);
}
