import type { Property } from "../types";
import { bedroomLabel, capitalise, formatKes } from "../format";

export function PropertyCard({ p }: { p: Property }) {
  return (
    <article className="card">
      <div className="card-top">
        <span className="card-type">{capitalise(p.property_type)}</span>
        <span className={p.furnished ? "badge badge-on" : "badge"}>{p.furnished ? "Furnished" : "Unfurnished"}</span>
      </div>
      <h3 className="card-title">{p.title}</h3>
      <p className="card-loc">
        {p.neighbourhood === p.location ? p.location : `${p.neighbourhood}, ${p.location}`} · {p.county} County
      </p>
      <div className="card-price">
        {formatKes(p.price_kes)}
        <span>/month</span>
      </div>
      <ul className="card-facts">
        <li>{bedroomLabel(p.property_type, p.bedrooms)}</li>
        <li>
          {p.bathrooms} bath{p.bathrooms === 1 ? "" : "s"}
        </li>
        <li className="card-id">#{p.id}</li>
      </ul>
      <p className="card-desc">{p.description}</p>
    </article>
  );
}
