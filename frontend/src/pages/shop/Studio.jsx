import { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  Bookmark,
  Check,
  ExternalLink,
  Images,
  Loader2,
  Printer,
  RefreshCw,
  ShoppingBag,
  Sparkles,
  Trash2,
  Wand2,
  XCircle,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { designsApi } from '../../api';
import {
  IN_FLIGHT,
  cardTitle,
  pollIntervalFor,
  promptFromSaved,
  quotaLabel,
  statusTone,
} from '../../lib/studio';

// The AI poster studio (AIP-06): a customer describes a poster, the designs
// service renders it asynchronously, the page polls the row until it is ready
// or failed, and a ready design can be printed (an unlisted catalog family the
// existing product page and cart sell) or its prompt saved for later. Three
// tabs: Generate / My designs / Saved prompts. Every request goes through
// designsApi with the customer bearer; the image itself is a public URL.

const TABS = [
  { id: 'generate', label: 'Generate', icon: Wand2 },
  { id: 'designs', label: 'My designs', icon: Images },
  { id: 'saved', label: 'Saved prompts', icon: Bookmark },
];

const STATUS_LABELS = {
  queued: 'Queued',
  generating: 'Generating',
  ready: 'Ready',
  failed: 'Failed',
};

const PRIMARY_BUTTON =
  'inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
const SECONDARY_BUTTON =
  'inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-700 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed';

function Spinner({ text }) {
  return (
    <div className="text-center py-12">
      <div className="w-12 h-12 mx-auto mb-4 rounded-full border-4 border-orange-500 border-t-transparent animate-spin" />
      <p className="text-stone-500">{text}</p>
    </div>
  );
}

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusTone(status)}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

// Inline "give it a title" form shared by the card and the Generate form.
// Submitting with an empty title falls back to the default the caller passes.
function SaveTitleForm({ defaultTitle, onSave, onCancel, pending }) {
  const [title, setTitle] = useState('');
  return (
    <form
      className="flex items-center gap-2 mt-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSave((title.trim() || defaultTitle || 'Untitled prompt').slice(0, 120));
      }}
    >
      <input
        type="text"
        value={title}
        maxLength={120}
        autoFocus
        onChange={(e) => setTitle(e.target.value)}
        placeholder={defaultTitle || 'Title'}
        className="flex-1 min-w-0 px-3 py-1.5 rounded-lg border border-stone-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500/30 focus:border-orange-400"
      />
      <button type="submit" disabled={pending} className={PRIMARY_BUTTON}>
        {pending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
        Save
      </button>
      <button type="button" onClick={onCancel} className={SECONDARY_BUTTON}>
        Cancel
      </button>
    </form>
  );
}

// One design: the portrait frame (image / spinner / failure), the title, the
// status badge, the "Bought" marker and the actions. `large` is the Generate
// tab's preview; the grid in "My designs" renders the compact version.
function DesignCard({ gen, onPrint, onSave, printing, saving, large }) {
  const [savingOpen, setSavingOpen] = useState(false);
  const inFlight = IN_FLIGHT.includes(gen.status);
  const personalised = gen.personalise && gen.effective_prompt && gen.effective_prompt !== gen.prompt;

  return (
    <div className="bg-white rounded-2xl border border-stone-200 p-3 flex flex-col gap-3">
      <div className="aspect-[2/3] bg-stone-100 rounded-xl overflow-hidden flex items-center justify-center">
        {gen.status === 'ready' && gen.image_url ? (
          <img src={gen.image_url}
            alt={gen.prompt}
            loading={large ? 'eager' : 'lazy'}
            className="w-full h-full object-cover"
          />
        ) : inFlight ? (
          <div className="text-center text-stone-500 px-4">
            <Loader2 className="w-8 h-8 mx-auto mb-3 text-orange-500 animate-spin" />
            <p className="text-sm font-medium">{gen.status === 'generating' ? 'Generating…' : 'Queued…'}</p>
            {large && <p className="text-xs text-stone-400 mt-1">Checking every 2 seconds</p>}
          </div>
        ) : (
          <div className="w-full h-full bg-red-50 text-red-800 p-4 flex flex-col items-center justify-center text-center">
            <XCircle className="w-8 h-8 mb-3 text-red-500" />
            <p className="text-sm font-medium">Generation failed</p>
            <p className="text-xs mt-1 text-red-700">{gen.failure_reason || 'No reason was given.'}</p>
          </div>
        )}
      </div>

      <div className="min-w-0">
        <p className={`font-medium text-stone-900 truncate ${large ? 'text-base' : 'text-sm'}`} title={gen.prompt}>
          {cardTitle(gen) || 'Untitled'}
        </p>
        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
          <StatusBadge status={gen.status} />
          {gen.purchased_at && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
              <ShoppingBag className="w-3 h-3" />
              Bought
            </span>
          )}
          {gen.personalise && (
            <span
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-violet-100 text-violet-800"
              title={personalised ? gen.effective_prompt : 'Personalise was on, but no style notes were available yet'}
            >
              <Sparkles className="w-3 h-3" />
              Personalised
            </span>
          )}
        </div>
        {large && personalised && (
          <p className="mt-2 text-xs text-stone-500 whitespace-pre-line" title="What was actually sent to the provider">
            {gen.effective_prompt.slice(gen.prompt.length).trim()}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {gen.product_url ? (
          <Link to={gen.product_url} className={PRIMARY_BUTTON}>
            <ExternalLink className="w-4 h-4" />
            View product
          </Link>
        ) : gen.status === 'ready' ? (
          <button type="button" onClick={() => onPrint?.(gen.id)} disabled={printing || !onPrint} className={PRIMARY_BUTTON}>
            {printing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Printer className="w-4 h-4" />}
            Print this
          </button>
        ) : null}
        {onSave && !savingOpen && (
          <button type="button" onClick={() => setSavingOpen(true)} className={SECONDARY_BUTTON}>
            <Bookmark className="w-4 h-4" />
            Save prompt
          </button>
        )}
      </div>
      {onSave && savingOpen && (
        <SaveTitleForm
          defaultTitle={cardTitle(gen)}
          pending={saving}
          onCancel={() => setSavingOpen(false)}
          onSave={(title) => {
            onSave({ title, prompt: gen.prompt });
            setSavingOpen(false);
          }}
        />
      )}
    </div>
  );
}

export default function Studio() {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState('generate');
  const [prompt, setPrompt] = useState('');
  const [personalise, setPersonalise] = useState(false);
  const [currentId, setCurrentId] = useState(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [notice, setNotice] = useState(null); // { tone: 'error' | 'success', text }

  // ---- queries -------------------------------------------------------------
  const quota = useQuery({
    queryKey: ['quota'],
    queryFn: designsApi.getQuota,
    enabled: isAuthenticated,
    staleTime: 10000,
  });

  const profile = useQuery({
    queryKey: ['style-profile'],
    queryFn: designsApi.getStyleProfile,
    enabled: isAuthenticated && (personalise || tab === 'generate'),
  });

  // The design being watched: polled every 2 s only while queued/generating
  // (pollIntervalFor answers false once it is ready or failed).
  const current = useQuery({
    queryKey: ['design', currentId],
    queryFn: () => designsApi.getGeneration(currentId),
    enabled: isAuthenticated && !!currentId,
    refetchInterval: (query) => pollIntervalFor(query.state.data?.status),
  });

  const designs = useQuery({
    queryKey: ['designs'],
    queryFn: () => designsApi.listGenerations(),
    enabled: isAuthenticated && tab === 'designs',
    refetchInterval: (query) =>
      (query.state.data ?? []).some((g) => IN_FLIGHT.includes(g.status)) ? 3000 : false,
  });

  const saved = useQuery({
    queryKey: ['saved-prompts'],
    queryFn: designsApi.listSavedPrompts,
    enabled: isAuthenticated && (tab === 'saved' || tab === 'generate'),
  });

  // ---- mutations -----------------------------------------------------------
  const generate = useMutation({
    mutationFn: () => designsApi.createGeneration({ prompt: prompt.trim(), personalise }),
    onSuccess: (data) => {
      // Seed the cache with the 202 body so the card shows "Queued" at once.
      queryClient.setQueryData(['design', data.id], data);
      setCurrentId(data.id);
      setNotice(null);
      queryClient.invalidateQueries({ queryKey: ['quota'] });
      queryClient.invalidateQueries({ queryKey: ['designs'] });
    },
    // 429 arrives from authFetchJSON as the quota detail plus a human wait —
    // "Daily limit of 10 generations reached — try again in 6 h 7 min (at 02:00)."
    // (see rateLimitError in api.js); 422 / 5xx carry the service's detail.
    // All are already human-readable.
    onError: (err) => setNotice({ tone: 'error', text: err.message }),
  });

  const print = useMutation({
    mutationFn: (id) => designsApi.printGeneration(id),
    onSuccess: (data, id) => {
      queryClient.invalidateQueries({ queryKey: ['design', id] });
      queryClient.invalidateQueries({ queryKey: ['designs'] });
      setNotice({
        tone: 'success',
        text: data.created ? `Product created — ${data.sku}` : `Product already existed — ${data.sku}`,
      });
    },
    onError: (err) => setNotice({ tone: 'error', text: err.message }),
  });

  const savePrompt = useMutation({
    mutationFn: ({ title, prompt: p }) => designsApi.createSavedPrompt({ title, prompt: p }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-prompts'] });
      setNotice({ tone: 'success', text: 'Prompt saved' });
    },
    onError: (err) => setNotice({ tone: 'error', text: err.message }),
  });

  const deleteSaved = useMutation({
    mutationFn: (id) => designsApi.deleteSavedPrompt(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['saved-prompts'] }),
    onError: (err) => setNotice({ tone: 'error', text: err.message }),
  });

  const refreshProfile = useMutation({
    mutationFn: designsApi.refreshStyleProfile,
    onSuccess: (data) => queryClient.setQueryData(['style-profile'], data),
    onError: (err) => setNotice({ tone: 'error', text: err.message }),
  });

  // ---- auth gate (MyOrders precedent) --------------------------------------
  if (authLoading) {
    return (
      <div className="max-w-6xl mx-auto px-4 py-20">
        <Spinner text="Loading..." />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/shop/login" state={{ from: '/shop/studio' }} replace />;
  }

  const canGenerate = prompt.trim().length >= 3 && !generate.isPending;
  const profileData = profile.data;
  const quotaText = quotaLabel(quota.data);

  const applySavedPrompt = (s) => {
    setPrompt(promptFromSaved(s));
    setTab('generate');
    setNotice(null);
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-stone-900 mb-2 flex items-center gap-2">
          <Sparkles className="w-7 h-7 text-orange-500" />
          AI Poster Studio
        </h1>
        <p className="text-stone-500">Describe a poster, preview it, print it.</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-6 border-b border-stone-200 mb-8">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`-mb-px pb-3 inline-flex items-center gap-2 text-sm font-medium transition-colors ${
                tab === t.id
                  ? 'border-b-2 border-orange-500 text-orange-600'
                  : 'border-b-2 border-transparent text-stone-500 hover:text-stone-900'
              }`}
            >
              <Icon className="w-4 h-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {notice && (
        <div
          className={`mb-6 flex items-start gap-2 px-4 py-3 rounded-xl text-sm ${
            notice.tone === 'error'
              ? 'bg-red-50 text-red-800 border border-red-200'
              : 'bg-emerald-50 text-emerald-800 border border-emerald-200'
          }`}
        >
          {notice.tone === 'error' ? (
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          ) : (
            <Check className="w-4 h-4 mt-0.5 shrink-0" />
          )}
          <span className="flex-1">{notice.text}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-xs underline opacity-70 hover:opacity-100">
            Dismiss
          </button>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {tab === 'generate' && (
        <div className="grid gap-8 md:grid-cols-[minmax(0,1fr)_18rem] lg:grid-cols-[minmax(0,1fr)_22rem]">
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault();
              if (canGenerate) generate.mutate();
            }}
          >
            <div>
              <label htmlFor="studio-prompt" className="block text-sm font-medium text-stone-700 mb-2">
                Describe your poster
              </label>
              <textarea
                id="studio-prompt"
                rows={5}
                maxLength={2000}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="A minimalist travel poster of Belgrade at dawn…"
                className="w-full px-4 py-3 rounded-xl border border-stone-200 bg-white text-stone-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-orange-500/30 focus:border-orange-400 resize-y"
              />
              <p className="text-xs text-stone-400 mt-1 text-right">{prompt.length} / 2000</p>
            </div>

            <div className="rounded-xl border border-stone-200 bg-white p-4">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={personalise}
                  onChange={(e) => setPersonalise(e.target.checked)}
                  className="w-4 h-4 rounded border-stone-300 text-orange-500 focus:ring-orange-500"
                />
                <span className="text-sm font-medium text-stone-900">Personalise with my style profile</span>
              </label>
              {personalise && (
                <div className="mt-3 pl-7 text-sm">
                  {profile.isLoading ? (
                    <p className="text-stone-400">Loading your profile…</p>
                  ) : profileData?.summary ? (
                    <p className="text-stone-700 italic">“{profileData.summary}”</p>
                  ) : (
                    <p className="text-stone-500">No profile yet — generate a few posters or buy one, then refresh.</p>
                  )}
                  <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-stone-500">
                    {profileData && (
                      <span>
                        {profileData.prompt_count} prompt{profileData.prompt_count === 1 ? '' : 's'} ·{' '}
                        {profileData.purchase_count} purchase{profileData.purchase_count === 1 ? '' : 's'}
                      </span>
                    )}
                    {profileData?.stale && <span className="text-amber-700">Profile is out of date</span>}
                    <button
                      type="button"
                      onClick={() => refreshProfile.mutate()}
                      disabled={refreshProfile.isPending}
                      className="inline-flex items-center gap-1 text-orange-600 hover:text-orange-700 disabled:opacity-50"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${refreshProfile.isPending ? 'animate-spin' : ''}`} />
                      Refresh profile
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button type="submit" disabled={!canGenerate} className={PRIMARY_BUTTON}>
                {generate.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
                Generate
              </button>
              {!saveOpen && (
                <button
                  type="button"
                  onClick={() => setSaveOpen(true)}
                  disabled={prompt.trim().length < 3}
                  className={SECONDARY_BUTTON}
                >
                  <Bookmark className="w-4 h-4" />
                  Save prompt
                </button>
              )}
              {quotaText && (
                <span className="text-xs text-stone-500" title={quota.data?.resets_at ? `Resets ${new Date(quota.data.resets_at).toLocaleString()}` : undefined}>
                  {quotaText}
                </span>
              )}
            </div>
            {saveOpen && (
              <SaveTitleForm
                defaultTitle={cardTitle({ prompt })}
                pending={savePrompt.isPending}
                onCancel={() => setSaveOpen(false)}
                onSave={(title) => {
                  savePrompt.mutate({ title, prompt: prompt.trim() });
                  setSaveOpen(false);
                }}
              />
            )}

            {saved.data?.length > 0 && (
              <div className="pt-2">
                <p className="text-xs font-medium text-stone-500 uppercase tracking-wide mb-2">Start from a saved prompt</p>
                <div className="flex flex-wrap gap-2">
                  {saved.data.slice(0, 6).map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => applySavedPrompt(s)}
                      title={s.prompt}
                      className="px-3 py-1.5 rounded-full border border-stone-200 bg-white text-xs text-stone-700 hover:border-orange-300 hover:text-orange-700 transition-colors"
                    >
                      {s.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </form>

          <div>
            {!currentId ? (
              <div className="aspect-[2/3] rounded-2xl border-2 border-dashed border-stone-200 bg-white flex flex-col items-center justify-center text-center p-6">
                <div className="w-16 h-16 mb-4 rounded-2xl bg-stone-100 flex items-center justify-center">
                  <Images className="w-8 h-8 text-stone-400" />
                </div>
                <p className="font-medium text-stone-900">Your poster will appear here</p>
                <p className="text-sm text-stone-500 mt-1">Portrait, 2:3 — printable from A4 to A1.</p>
              </div>
            ) : current.isError ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
                <p className="font-medium">Could not load this design</p>
                <p className="mt-1">{current.error.message}</p>
              </div>
            ) : current.data ? (
              <DesignCard
                gen={current.data}
                large
                printing={print.isPending && print.variables === current.data.id}
                saving={savePrompt.isPending}
                onPrint={(id) => print.mutate(id)}
                onSave={(payload) => savePrompt.mutate(payload)}
              />
            ) : (
              <Spinner text="Submitting…" />
            )}
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {tab === 'designs' && (
        designs.isLoading ? (
          <Spinner text="Loading your designs..." />
        ) : designs.isError ? (
          <div className="text-center py-12">
            <XCircle className="w-10 h-10 mx-auto mb-3 text-red-500" />
            <p className="text-stone-900 font-medium mb-1">Failed to load designs</p>
            <p className="text-stone-500 text-sm">{designs.error.message}</p>
          </div>
        ) : designs.data?.length > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {designs.data.map((gen) => (
              <DesignCard
                key={gen.id}
                gen={gen}
                printing={print.isPending && print.variables === gen.id}
                saving={savePrompt.isPending}
                onPrint={(id) => print.mutate(id)}
                onSave={(payload) => savePrompt.mutate(payload)}
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-stone-100 flex items-center justify-center">
              <Images className="w-10 h-10 text-stone-400" />
            </div>
            <h2 className="text-xl font-semibold text-stone-900 mb-2">No designs yet</h2>
            <p className="text-stone-500 mb-8">Generate your first poster and it will show up here.</p>
            <button type="button" onClick={() => setTab('generate')} className={PRIMARY_BUTTON}>
              <Wand2 className="w-4 h-4" />
              Generate a poster
            </button>
          </div>
        )
      )}

      {/* ---------------------------------------------------------------- */}
      {tab === 'saved' && (
        saved.isLoading ? (
          <Spinner text="Loading saved prompts..." />
        ) : saved.isError ? (
          <div className="text-center py-12">
            <XCircle className="w-10 h-10 mx-auto mb-3 text-red-500" />
            <p className="text-stone-900 font-medium mb-1">Failed to load saved prompts</p>
            <p className="text-stone-500 text-sm">{saved.error.message}</p>
          </div>
        ) : saved.data?.length > 0 ? (
          <div className="grid gap-3">
            {saved.data.map((s) => (
              <div
                key={s.id}
                className="bg-white rounded-2xl border border-stone-200 p-5 flex flex-col sm:flex-row sm:items-center gap-4"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-stone-900 truncate">{s.title}</p>
                  <p className="text-sm text-stone-600 line-clamp-2 mt-1">{s.prompt}</p>
                  <p className="text-xs text-stone-400 mt-2">
                    Saved {new Date(s.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button type="button" onClick={() => applySavedPrompt(s)} className={PRIMARY_BUTTON}>
                    <Wand2 className="w-4 h-4" />
                    Use
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteSaved.mutate(s.id)}
                    disabled={deleteSaved.isPending && deleteSaved.variables === s.id}
                    className={`${SECONDARY_BUTTON} text-red-600 hover:bg-red-50`}
                  >
                    {deleteSaved.isPending && deleteSaved.variables === s.id ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-stone-100 flex items-center justify-center">
              <Bookmark className="w-10 h-10 text-stone-400" />
            </div>
            <h2 className="text-xl font-semibold text-stone-900 mb-2">No saved prompts yet</h2>
            <p className="text-stone-500 mb-8">Save one from the Generate tab and reuse it here.</p>
            <button type="button" onClick={() => setTab('generate')} className={PRIMARY_BUTTON}>
              <Wand2 className="w-4 h-4" />
              Go to Generate
            </button>
          </div>
        )
      )}
    </div>
  );
}
