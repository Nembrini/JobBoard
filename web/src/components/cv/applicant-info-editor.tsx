"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus, RotateCcw, Sparkles, Trash2 } from "lucide-react";

import { AreaTesto, BottoneAggiungi, Campo, Targhetta } from "@/components/cv/fields";
import {
  derivaInformazioniDalProfilo,
  nuovoIdInfo,
  type ApplicantInfoBank,
  type ApplicantInfoItem,
} from "@/lib/applicant-info";
import { salvaInformazioniApplicante } from "@/lib/applicant-info-actions";
import type { MasterProfile } from "@/lib/master-profile";

/**
 * La sezione "Informazioni applicante": il pool libero che la Fase 6 può
 * pescare in aggiunta al CV, scegliendo le voci pertinenti annuncio per
 * annuncio.
 *
 * Due modelli di scrittura convivono qui, e non è una svista:
 *
 * - **l'elenco esistente** segue lo stesso "un solo stato, un solo salvataggio"
 *   di `ProfileEditor` — modificare o cancellare una voce è una mutazione
 *   locale finché non si preme "Salva le modifiche", cosa che rende "Annulla"
 *   un vero annullamento;
 * - **le proposte dal CV** si salvano invece una per una, subito: sono voci
 *   che non esistono ancora da nessuna parte nel pool, "salvabile" per ognuna
 *   significa letteralmente un bottone che la salva, non un altro giro di
 *   stato locale da ricordarsi di confermare.
 */
export function ApplicantInfoEditor({
  iniziale,
  profilo,
}: {
  iniziale: ApplicantInfoBank;
  profilo: MasterProfile | null;
}) {
  const router = useRouter();
  const [base, setBase] = useState(iniziale);
  const [bank, setBank] = useState(iniziale);
  const [errore, setErrore] = useState<string | null>(null);
  const [salvato, setSalvato] = useState(false);
  const [inCorso, startTransition] = useTransition();

  const modificato = JSON.stringify(bank) !== JSON.stringify(base);

  function muta(fn: (b: ApplicantInfoBank) => ApplicantInfoBank) {
    setBank(fn);
    setSalvato(false);
  }

  async function salva(nuovo: ApplicantInfoBank) {
    const esito = await salvaInformazioniApplicante(nuovo);
    if (!esito.ok) throw new Error(esito.errore);
    setBase(nuovo);
    setBank(nuovo);
  }

  function salvaModifiche() {
    setErrore(null);
    startTransition(async () => {
      try {
        await salva(bank);
        setSalvato(true);
        router.refresh();
      } catch (e) {
        setErrore(e instanceof Error ? e.message : "salvataggio fallito");
      }
    });
  }

  /** Una proposta dal CV, salvata da sola: entra nel pool con un id nuovo. */
  async function salvaProposta(proposta: { label: string; text: string }) {
    const voce: ApplicantInfoItem = {
      id: nuovoIdInfo(proposta.label, base),
      label: proposta.label,
      text: proposta.text,
    };
    const nuovo = { items: [...base.items, voce] };
    await salva(nuovo);
    router.refresh();
  }

  return (
    <section className="space-y-4">
      <div className="border-b pb-2">
        <h2 className="font-heading flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Informazioni applicante
          <span className="num text-muted-foreground text-sm font-normal">{bank.items.length}</span>
        </h2>
        <p className="text-muted-foreground mt-1 max-w-2xl text-sm leading-relaxed">
          Fatti veri sul tuo conto non ancora dentro il CV — una disponibilità, un
          risultato citato solo a voce, una certificazione. Quando generi un CV su
          misura, il modello ne sceglie al massimo tre, solo se pertinenti per
          quell&apos;annuncio: il resto del pool resta a disposizione senza forzare
          niente nel documento.
        </p>
      </div>

      {profilo ? <ProposteDalCv profilo={profilo} bank={base} onSalva={salvaProposta} /> : null}

      <div className="space-y-4">
        {bank.items.map((voce, i) => (
          <VoceCard
            key={voce.id}
            voce={voce}
            onChange={(patch) =>
              muta((b) => ({
                items: b.items.map((v, j) => (j === i ? { ...v, ...patch } : v)),
              }))
            }
            onElimina={() => muta((b) => ({ items: b.items.filter((_, j) => j !== i) }))}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <BottoneAggiungi
          onClick={() =>
            muta((b) => ({
              items: [
                ...b.items,
                {
                  id: nuovoIdInfo("nuova-informazione", b),
                  label: "",
                  text: "",
                },
              ],
            }))
          }
        >
          Aggiungi informazione
        </BottoneAggiungi>

        {bank.items.length > 0 ? <BottoneCancellaTutte onConferma={() => muta(() => ({ items: [] }))} /> : null}
      </div>

      <BarraSalvataggioInfo
        modificato={modificato}
        inCorso={inCorso}
        errore={errore}
        salvato={salvato}
        onSalva={salvaModifiche}
        onAnnulla={() => {
          setBank(base);
          setErrore(null);
        }}
      />
    </section>
  );
}

function VoceCard({
  voce,
  onChange,
  onElimina,
}: {
  voce: ApplicantInfoItem;
  onChange: (patch: Partial<ApplicantInfoItem>) => void;
  onElimina: () => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
          <span className="font-medium">{voce.label || "Nuova informazione"}</span>
          <Targhetta id={voce.id} />
        </div>
        <button
          type="button"
          onClick={onElimina}
          aria-label={`Elimina ${voce.label || "informazione"}`}
          title="Cancella singolo"
          className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive grid size-9 shrink-0 place-items-center rounded-md transition-colors"
        >
          <Trash2 className="size-4" />
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-[14rem_1fr]">
        <Campo
          etichetta="Etichetta"
          segnaposto="Disponibilità, Motivazione, Progetto extra..."
          valore={voce.label}
          onChange={(v) => onChange({ label: v })}
        />
        <AreaTesto
          etichetta="Testo"
          righe={2}
          massimo={2000}
          valore={voce.text}
          onChange={(v) => onChange({ text: v })}
        />
      </div>
    </div>
  );
}

function BottoneCancellaTutte({ onConferma }: { onConferma: () => void }) {
  const [chiede, setChiede] = useState(false);

  if (chiede) {
    return (
      <div className="border-destructive/40 bg-destructive/5 inline-flex h-10 items-center gap-2 rounded-lg border px-3 text-sm">
        <span>Cancellare tutte le voci?</span>
        <button
          type="button"
          onClick={() => {
            onConferma();
            setChiede(false);
          }}
          className="text-destructive font-medium underline underline-offset-2"
        >
          Conferma
        </button>
        <button type="button" onClick={() => setChiede(false)} className="text-muted-foreground underline underline-offset-2">
          Annulla
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setChiede(true)}
      className="border-input hover:bg-accent text-muted-foreground hover:text-destructive inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium"
    >
      <Trash2 className="size-4" />
      Cancella tutte le informazioni
    </button>
  );
}

/**
 * Le voci che il CV rivisto suggerisce e che il pool non ha ancora salvate.
 *
 * Il ricalcolo è già "live" (dipende solo dal profilo e dal pool attuali): il
 * bottone "Carica informazioni tramite CV" non nasconde un'estrazione che gira
 * solo al click, mostra semplicemente lo stesso elenco già calcolato, per chi
 * preferisce un'azione esplicita a un elenco che compare da solo.
 */
function ProposteDalCv({
  profilo,
  bank,
  onSalva,
}: {
  profilo: MasterProfile;
  bank: ApplicantInfoBank;
  onSalva: (proposta: { label: string; text: string }) => Promise<void>;
}) {
  const proposte = useMemo(() => derivaInformazioniDalProfilo(profilo, bank), [profilo, bank]);
  const [salvando, setSalvando] = useState<number | null>(null);
  const [errore, setErrore] = useState<string | null>(null);

  if (proposte.length === 0) return null;

  return (
    <div className="space-y-3 rounded-xl border border-dashed p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="text-muted-foreground size-4" />
          Trovate nel CV, non ancora salvate qui
        </p>
      </div>
      {errore ? (
        <p role="alert" className="text-destructive text-sm">
          {errore}
        </p>
      ) : null}
      <ul className="space-y-2">
        {proposte.map((proposta, i) => (
          <li
            key={`${proposta.label}-${i}`}
            className="bg-muted/40 flex flex-wrap items-center justify-between gap-3 rounded-lg p-3 text-sm"
          >
            <span>
              <span className="text-muted-foreground">{proposta.label}: </span>
              {proposta.text}
            </span>
            <button
              type="button"
              disabled={salvando !== null}
              onClick={async () => {
                setErrore(null);
                setSalvando(i);
                try {
                  await onSalva(proposta);
                } catch (e) {
                  setErrore(e instanceof Error ? e.message : "salvataggio fallito");
                } finally {
                  setSalvando(null);
                }
              }}
              className="border-input hover:bg-accent inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium disabled:opacity-50"
            >
              {salvando === i ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
              Salva
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function BarraSalvataggioInfo({
  modificato,
  inCorso,
  errore,
  salvato,
  onSalva,
  onAnnulla,
}: {
  modificato: boolean;
  inCorso: boolean;
  errore: string | null;
  salvato: boolean;
  onSalva: () => void;
  onAnnulla: () => void;
}) {
  if (!modificato) {
    return salvato ? (
      <p role="status" className="text-muted-foreground text-sm">
        Informazioni salvate.
      </p>
    ) : null;
  }

  return (
    <div className="bg-background/95 fixed inset-x-0 bottom-0 z-40 border-t backdrop-blur">
      <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <p className="text-sm">
          {errore ? <span className="text-destructive">{errore}</span> : "Ci sono modifiche non salvate."}
        </p>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onAnnulla}
            disabled={inCorso}
            className="border-input hover:bg-accent inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-50"
          >
            <RotateCcw className="size-4" />
            Annulla
          </button>
          <button
            type="button"
            onClick={onSalva}
            disabled={inCorso}
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-10 items-center gap-2 rounded-lg px-5 text-sm font-medium disabled:opacity-60"
          >
            {inCorso ? <Loader2 className="size-4 animate-spin" /> : null}
            Salva le modifiche
          </button>
        </div>
      </div>
    </div>
  );
}
