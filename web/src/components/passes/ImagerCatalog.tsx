import type { CatalogImager, PassCatalog, SkippedImager } from "../../api/types";
import { utc } from "../../lib/format";
import { skipReasonText } from "../../lib/passes";

/**
 * The imagers the model counts, each field of regard with the public source
 * it was assumed from, and the age of the element set behind it. Imagers
 * the engine had to skip are listed outside the collapsed table: a skipped
 * imager's passes are missing, so gaps can look longer than they are.
 */
export function ImagerCatalog({ catalog }: { catalog: PassCatalog }) {
  return (
    <section className="imager-catalog" aria-label="Imaging catalog">
      {catalog.skipped.length > 0 && <SkippedBanner skipped={catalog.skipped} />}
      <details>
        <summary>
          Imaging catalog · {catalog.imagers.length} imagers · fields of regard are planning assumptions
        </summary>
        <table className="data-table">
          <thead>
            <tr>
              <th>imager</th>
              <th>NORAD</th>
              <th>sensor</th>
              <th>max off-nadir</th>
              <th>GSD</th>
              <th>element age</th>
              <th>assumption source</th>
            </tr>
          </thead>
          <tbody>
            {catalog.imagers.map((imager) => (
              <ImagerRow key={imager.norad_id} imager={imager} />
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

function ImagerRow({ imager }: { imager: CatalogImager }) {
  return (
    <tr className={imager.stale ? "warn" : ""}>
      <td>{imager.name}</td>
      <td className="num">{imager.norad_id}</td>
      <td>{imager.sensor}</td>
      <td className="num">{`${imager.max_off_nadir_deg.toFixed(1)}°`}</td>
      <td className="num">{imager.gsd_m === null ? "-" : `${imager.gsd_m} m`}</td>
      <td className="num" title={imager.element_epoch ? `element epoch ${utc(imager.element_epoch)}` : undefined}>
        {imager.element_age_days === null ? "-" : `${imager.element_age_days.toFixed(1)} d`}
        {imager.stale && (
          <>
            {" "}
            <span className="chip chip-stale">STALE</span>
          </>
        )}
      </td>
      <td className="basis">{imager.basis}</td>
    </tr>
  );
}

function SkippedBanner({ skipped }: { skipped: SkippedImager[] }) {
  const n = skipped.length;
  return (
    <div className="answer-note warn" role="note">
      {n} catalogued imager{n === 1 ? "" : "s"} skipped. Skipped passes are not in the timeline, so gaps may be longer
      than shown.
      <ul className="skipped-list">
        {skipped.map((s) => (
          <li key={`${s.norad_id}-${s.name}`}>
            {s.name} (NORAD {s.norad_id}): {skipReasonText(s.reason)}
          </li>
        ))}
      </ul>
    </div>
  );
}
