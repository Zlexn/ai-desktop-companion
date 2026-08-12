import { useEffect, useMemo, useState } from 'react';
import type {
  PersonaActivateRequest,
  PersonaArtifact,
  PersonaCapabilities,
  PersonaConfig,
  PersonaCreateRequest,
  PersonaRedactRequest,
} from '../api/types';

interface PersonaPanelProps {
  current: PersonaArtifact | null;
  artifacts: PersonaArtifact[];
  capabilities: PersonaCapabilities | null;
  loading: boolean;
  error: string | null;
  onRetry: () => Promise<void>;
  onCreate: (request: PersonaCreateRequest) => Promise<void>;
  onActivate: (request: PersonaActivateRequest) => Promise<void>;
  onRedact: (artifactId: string, request: PersonaRedactRequest) => Promise<void>;
}

function cloneConfig(config: PersonaConfig): PersonaConfig {
  return JSON.parse(JSON.stringify(config)) as PersonaConfig;
}

function lines(values: string[]): string {
  return values.join('\n');
}

function parseLines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean);
}

export function PersonaPanel({
  current,
  artifacts,
  capabilities,
  loading,
  error,
  onRetry,
  onCreate,
  onActivate,
  onRedact,
}: PersonaPanelProps) {
  const [draft, setDraft] = useState<PersonaConfig | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  useEffect(() => {
    if (current?.config) setDraft(cloneConfig(current.config));
  }, [current?.id]);

  const changedFields = useMemo(() => {
    if (!current?.config || !draft) return [];
    const fields: Array<[string, unknown, unknown]> = [
      ['名称', current.config.identity.name, draft.identity.name],
      ['物种', current.config.identity.species, draft.identity.species],
      ['角色', current.config.identity.role, draft.identity.role],
      ['背景', current.config.background, draft.background],
      ['核心特质', current.config.personality.core_traits, draft.personality.core_traits],
      ['价值观', current.config.personality.values, draft.personality.values],
      ['语气', current.config.language_style.tone, draft.language_style.tone],
      ['语言习惯', current.config.language_style.habits, draft.language_style.habits],
      ['初始关系', current.config.relationship.initial, draft.relationship.initial],
      ['额外禁止项', current.config.additional_prohibitions, draft.additional_prohibitions],
    ];
    return fields
      .filter(([, before, after]) => JSON.stringify(before) !== JSON.stringify(after))
      .map(([label]) => label);
  }, [current, draft]);

  function updateDraft(mutator: (next: PersonaConfig) => void) {
    if (!draft) return;
    const next = cloneConfig(draft);
    mutator(next);
    setDraft(next);
  }

  return (
    <section className="persona-panel" aria-label="角色版本">
      <details>
        <summary>角色版本</summary>
        <p>角色设定保存在不可变版本中；这里只显示安全元数据，不显示编译提示词或完整指纹。</p>
        {error ? <p role="alert">{error}</p> : null}
        {error ? <button type="button" onClick={() => void onRetry()}>重新加载角色版本</button> : null}
        {loading ? <p>角色版本加载中……</p> : null}
        {current ? (
          <div>
            <h3>当前版本 v{current.version}</h3>
            <p>
              ruleset {current.ruleset_version} · template {current.template_version} · compiler {current.compiler_version}
            </p>
            <p>短指纹 {current.fingerprint_prefix ?? '不可用'} · {new Date(current.created_at).toLocaleString()}</p>
          </div>
        ) : null}
        {draft && current ? (
          <fieldset disabled={loading}>
            <legend>编辑并创建新版本</legend>
            <label>名称<input value={draft.identity.name} onChange={(event) => updateDraft((next) => { next.identity.name = event.currentTarget.value; })} /></label>
            <label>物种<input value={draft.identity.species} onChange={(event) => updateDraft((next) => { next.identity.species = event.currentTarget.value; })} /></label>
            <label>角色<input value={draft.identity.role} onChange={(event) => updateDraft((next) => { next.identity.role = event.currentTarget.value; })} /></label>
            <label>背景<textarea value={draft.background} onChange={(event) => updateDraft((next) => { next.background = event.currentTarget.value; })} /></label>
            <label>核心特质（每行一项）<textarea value={lines(draft.personality.core_traits)} onChange={(event) => updateDraft((next) => { next.personality.core_traits = parseLines(event.currentTarget.value); })} /></label>
            <label>价值观（每行一项）<textarea value={lines(draft.personality.values)} onChange={(event) => updateDraft((next) => { next.personality.values = parseLines(event.currentTarget.value); })} /></label>
            <label>语气<textarea value={draft.language_style.tone} onChange={(event) => updateDraft((next) => { next.language_style.tone = event.currentTarget.value; })} /></label>
            <label>语言习惯（每行一项）<textarea value={lines(draft.language_style.habits)} onChange={(event) => updateDraft((next) => { next.language_style.habits = parseLines(event.currentTarget.value); })} /></label>
            <label>初始关系<textarea value={draft.relationship.initial} onChange={(event) => updateDraft((next) => { next.relationship.initial = event.currentTarget.value; })} /></label>
            <label>额外禁止项（每行一项）<textarea value={lines(draft.additional_prohibitions)} onChange={(event) => updateDraft((next) => { next.additional_prohibitions = parseLines(event.currentTarget.value); })} /></label>
            <p>变更字段：{changedFields.length ? changedFields.join('、') : '无'}</p>
            {confirmation === 'create' ? (
              <div>
                <button type="button" onClick={() => { setConfirmation(null); void onCreate({ config: draft, expected_artifact_id: current.id, expected_generation: current.activation_generation }); }}>确认创建并启用</button>
                <button type="button" onClick={() => setConfirmation(null)}>取消</button>
              </div>
            ) : (
              <button type="button" disabled={changedFields.length === 0} onClick={() => setConfirmation('create')}>创建新版本</button>
            )}
          </fieldset>
        ) : null}
        <h3>历史版本</h3>
        <ul>
          {artifacts.map((artifact) => (
            <li key={artifact.id}>
              <strong>v{artifact.version}</strong>{artifact.active ? '（当前）' : ''} · {artifact.fingerprint_prefix ?? '内容已清除'}
              {artifact.payload_state === 'redacted' ? (
                <span> · 内容已清除</span>
              ) : !artifact.active && current ? (
                confirmation === `activate:${artifact.id}` ? (
                  <span>
                    <button type="button" onClick={() => { setConfirmation(null); void onActivate({ artifact_id: artifact.id, expected_artifact_id: current.id, expected_generation: current.activation_generation }); }}>确认启用</button>
                    <button type="button" onClick={() => setConfirmation(null)}>取消</button>
                  </span>
                ) : (
                  <button type="button" onClick={() => setConfirmation(`activate:${artifact.id}`)}>启用此版本</button>
                )
              ) : null}
              {artifact.payload_state !== 'redacted' && !artifact.active && current ? (
                confirmation === `redact:${artifact.id}` ? (
                  <span>
                    <button type="button" onClick={() => { setConfirmation(null); void onRedact(artifact.id, { expected_artifact_id: current.id, expected_generation: current.activation_generation, confirmation: 'redact_persona_payload' }); }}>确认永久清除内容</button>
                    <button type="button" onClick={() => setConfirmation(null)}>取消</button>
                  </span>
                ) : (
                  <button type="button" onClick={() => setConfirmation(`redact:${artifact.id}`)}>清除历史内容</button>
                )
              ) : null}
            </li>
          ))}
        </ul>
        {capabilities ? <p>Context Composer：{capabilities.context_composer ? '已启用' : '未启用'}；摘要注入：未启用。</p> : null}
      </details>
    </section>
  );
}
