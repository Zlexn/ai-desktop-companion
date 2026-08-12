import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { PersonaArtifact, PersonaCapabilities, PersonaConfig } from '../api/types';
import { PersonaPanel } from './PersonaPanel';

const config: PersonaConfig = {
  identity: { name: '林夕', species: '原创虚拟角色', role: '文字伙伴' },
  background: '安静书房',
  personality: { core_traits: ['温和'], values: ['准确'] },
  language_style: { tone: '克制', habits: ['简洁'] },
  relationship: { initial: '初次认识' },
  additional_prohibitions: ['不得编造'],
};

const current: PersonaArtifact = {
  id: 'persona-1',
  version: 1,
  payload_state: 'active',
  schema_version: 'persona-schema-v1',
  ruleset_version: 'persona-ruleset-v1',
  template_version: 'persona-template-v1',
  compiler_version: 'persona-compiler-v1',
  config,
  created_at: '2026-07-21T00:00:00Z',
  redacted_at: null,
  active: true,
  activation_generation: 3,
  fingerprint_prefix: 'abc123def456',
  outcome: 'current',
};

const capabilities: PersonaCapabilities = {
  persona_artifacts: true,
  context_composer: true,
  summary_processing: false,
  summary_injection: false,
  relationship_projection: false,
  remote_summary: 'not_configured',
};

const props = {
  current,
  artifacts: [current],
  capabilities,
  loading: false,
  error: null,
  onRetry: vi.fn(async () => undefined),
  onCreate: vi.fn(async () => undefined),
  onActivate: vi.fn(async () => undefined),
  onRedact: vi.fn(async () => undefined),
};

afterEach(cleanup);

describe('PersonaPanel', () => {
  it('shows safe current metadata and creates only after confirmation', async () => {
    const onCreate = vi.fn(async () => undefined);
    render(<PersonaPanel {...props} onCreate={onCreate} />);
    await userEvent.click(screen.getByText('角色版本'));

    expect(screen.getByText(/当前版本 v1/)).toBeInTheDocument();
    expect(screen.getByText(/短指纹 abc123def456/)).toBeInTheDocument();
    const name = screen.getByRole('textbox', { name: '名称' });
    await userEvent.clear(name);
    await userEvent.type(name, '新角色');
    expect(screen.getByText(/变更字段：名称/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '创建新版本' }));
    expect(onCreate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认创建并启用' }));
    expect(onCreate).toHaveBeenCalledWith({
      config: { ...config, identity: { ...config.identity, name: '新角色' } },
      expected_artifact_id: 'persona-1',
      expected_generation: 3,
    });
  });

  it('never renders redacted payload or compiled prompt', async () => {
    const redacted: PersonaArtifact = {
      ...current,
      id: 'persona-old',
      version: 0,
      payload_state: 'redacted',
      config: null,
      active: false,
      fingerprint_prefix: null,
      redacted_at: '2026-07-22T00:00:00Z',
    };
    render(<PersonaPanel {...props} artifacts={[current, redacted]} />);
    await userEvent.click(screen.getByText('角色版本'));

    expect(screen.getAllByText(/内容已清除/).length).toBeGreaterThan(0);
    expect(screen.queryByText('PRIVATE_PERSONA_SENTINEL')).not.toBeInTheDocument();
    expect(screen.queryByText(/系统提示词/)).not.toBeInTheDocument();
  });

  it('requires confirmation for activation and irreversible redaction', async () => {
    const historical = { ...current, id: 'persona-older', version: 0, active: false };
    const onActivate = vi.fn(async () => undefined);
    const onRedact = vi.fn(async () => undefined);
    render(
      <PersonaPanel
        {...props}
        artifacts={[current, historical]}
        onActivate={onActivate}
        onRedact={onRedact}
      />,
    );
    await userEvent.click(screen.getByText('角色版本'));
    await userEvent.click(screen.getByRole('button', { name: '启用此版本' }));
    expect(onActivate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认启用' }));
    expect(onActivate).toHaveBeenCalledWith({
      artifact_id: 'persona-older',
      expected_artifact_id: 'persona-1',
      expected_generation: 3,
    });

    await userEvent.click(screen.getByRole('button', { name: '清除历史内容' }));
    expect(onRedact).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认永久清除内容' }));
    expect(onRedact).toHaveBeenCalledWith('persona-older', {
      expected_artifact_id: 'persona-1',
      expected_generation: 3,
      confirmation: 'redact_persona_payload',
    });
  });
});
