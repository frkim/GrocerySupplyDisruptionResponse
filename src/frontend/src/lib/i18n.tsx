import {
  createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore,
  type ReactNode,
} from 'react';
import { LOCALES, readLanguagePreference, TranslationStore, type MessageParams } from './localization';

const I18nContext = createContext<TranslationStore | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new TranslationStore(readLanguagePreference()));
  useEffect(() => {
    store.resume();
    return () => store.pause();
  }, [store]);
  return <I18nContext.Provider value={store}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const store = useContext(I18nContext);
  if (!store) throw new Error('useI18n requires I18nProvider.');
  const revision = useSyncExternalStore(store.subscribe, store.getSnapshot);
  return useMemo(() => ({
    language: store.language,
    locale: LOCALES[store.language],
    setLanguage: store.setLanguage,
    t: (source: string, params?: MessageParams) => store.t(source, params),
    text: (source: string) => store.text(source),
    json: (value: unknown) => store.json(value),
    pending: store.pending,
    error: store.error,
    retry: store.retry,
  }), [store, revision]);
}
