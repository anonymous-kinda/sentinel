import { useId, useState, type FormEvent } from "react";
import type { PassUnit } from "../../api/types";
import { validateUnit, type UnitDraft, type UnitErrors } from "../../lib/passes";
import { useAction } from "../../lib/useAction";

/**
 * The unit whose exposure the tab reports: shown, edited or deleted here and
 * nowhere else. The position is edge-local (ADR-010) and the form says so.
 * Input is checked against the ICD's rules before it is sent; the server
 * checks again, and its refusal is shown as it gave it.
 */

// The pass model's defaults for a new unit: ground level, 30 min to react.
const NEW_UNIT: UnitDraft = { unit_id: "", lat_deg: "", lon_deg: "", alt_m: "0", reaction_time_min: "30" };

const FIELDS: { field: keyof PassUnit; label: string }[] = [
  { field: "unit_id", label: "Unit id" },
  { field: "lat_deg", label: "Latitude (deg)" },
  { field: "lon_deg", label: "Longitude (deg)" },
  { field: "alt_m", label: "Altitude (m)" },
  { field: "reaction_time_min", label: "Reaction time (min)" },
];

const toDraft = (u: PassUnit): UnitDraft => ({
  unit_id: u.unit_id,
  lat_deg: String(u.lat_deg),
  lon_deg: String(u.lon_deg),
  alt_m: String(u.alt_m),
  reaction_time_min: String(u.reaction_time_min),
});

export const PRIVACY_NOTE = "Stays on this node. The unit's position is never sent to the hub.";

interface Props {
  unit: PassUnit | null;
  readOnly: boolean;
  onSave: (unit: PassUnit) => Promise<unknown>;
  onDelete: () => Promise<unknown>;
}

export function UnitForm({ unit, readOnly, onSave, onDelete }: Props) {
  const [draft, setDraft] = useState<UnitDraft | null>(null);
  const [errors, setErrors] = useState<UnitErrors>({});
  const { busy, error: serverError, run: request, clearError } = useAction();

  function edit(from: UnitDraft) {
    setErrors({});
    clearError();
    setDraft(from);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const checked = validateUnit(draft);
    setErrors(checked.errors);
    if (!checked.unit) return;
    const valid = checked.unit;
    if (await request(() => onSave(valid), "Pass unit save failed")) setDraft(null);
  }

  return (
    <section className="card unit-form" aria-label="Unit">
      <h3 className="passes-head">Unit</h3>
      {draft ? (
        <UnitEditor
          draft={draft}
          errors={errors}
          busy={busy}
          onChange={setDraft}
          onSubmit={save}
          onCancel={() => setDraft(null)}
        />
      ) : unit ? (
        <>
          <UnitSummary unit={unit} />
          <div className="unit-actions">
            <button className="btn-small" disabled={readOnly || busy} onClick={() => edit(toDraft(unit))}>
              Edit
            </button>
            <button className="btn-small" disabled={readOnly || busy} onClick={() => void request(onDelete, "Pass unit delete failed")}>
              Delete
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="muted">No unit set on this node.</p>
          <div className="unit-actions">
            <button className="btn-primary" disabled={readOnly} onClick={() => edit(NEW_UNIT)}>
              Set unit
            </button>
          </div>
        </>
      )}
      {serverError && (
        <div className="form-error" role="alert">
          {serverError}
        </div>
      )}
      {readOnly && <p className="muted small">This node is read-only: the unit cannot be changed here.</p>}
      <p className="unit-privacy">{PRIVACY_NOTE}</p>
    </section>
  );
}

function UnitSummary({ unit }: { unit: PassUnit }) {
  return (
    <dl className="unit-summary">
      <div>
        <dt>unit</dt>
        <dd>{unit.unit_id}</dd>
      </div>
      <div>
        <dt>position (lat, lon)</dt>
        <dd>{`${unit.lat_deg.toFixed(4)}, ${unit.lon_deg.toFixed(4)}`}</dd>
      </div>
      <div>
        <dt>altitude</dt>
        <dd>{`${unit.alt_m} m`}</dd>
      </div>
      <div>
        <dt>reaction time</dt>
        <dd>{`${unit.reaction_time_min} min`}</dd>
      </div>
    </dl>
  );
}

function UnitEditor({
  draft,
  errors,
  busy,
  onChange,
  onSubmit,
  onCancel,
}: {
  draft: UnitDraft;
  errors: UnitErrors;
  busy: boolean;
  onChange: (draft: UnitDraft) => void;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
}) {
  const id = useId();
  return (
    <form className="unit-editor" onSubmit={onSubmit} noValidate>
      {FIELDS.map(({ field, label }) => {
        const inputId = `${id}-${field}`;
        const error = errors[field];
        return (
          <div className="unit-field" key={field}>
            <label htmlFor={inputId}>{label}</label>
            <input
              id={inputId}
              value={draft[field]}
              inputMode={field === "unit_id" ? "text" : "decimal"}
              autoComplete="off"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${inputId}-error` : undefined}
              onChange={(e) => onChange({ ...draft, [field]: e.target.value })}
            />
            {error && (
              <span className="form-error" id={`${inputId}-error`}>
                {error}
              </span>
            )}
          </div>
        );
      })}
      <div className="unit-actions">
        <button type="submit" className="btn-primary" disabled={busy}>
          Save
        </button>
        <button type="button" className="btn-small" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}
