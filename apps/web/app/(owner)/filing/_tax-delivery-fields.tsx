"use client";

import {useState} from "react";
import {Button} from "../../components/ui";
import styles from "./_tax-delivery.module.css";

export function TaxDeliveryFields({label,fields}: {label: string;fields: readonly {path: string;value: string}[]}) {
  const [page,setPage]=useState(0);const size=40;const pages=Math.max(1,Math.ceil(fields.length/size));
  const currentPage=Math.min(page,pages-1);
  return <section aria-label={label}>
    <p className="cardNote" aria-live="polite">{fields.length ? `${currentPage*size+1}–${Math.min((currentPage+1)*size,fields.length)} av ${fields.length} felt` : "Ingen skalarfelt i dokumentet."}</p>
    {fields.length ? <table className={styles.fields}><caption className="srOnly">{label}</caption>
      <thead><tr><th scope="col">Felt</th><th scope="col">Verdi</th></tr></thead>
      <tbody>{fields.slice(currentPage*size,(currentPage+1)*size).map((field,index)=><tr key={field.path+":"+index}>
        <th scope="row">{field.path}</th><td>{field.value==="False"?"Nei":field.value==="True"?"Ja":field.value}</td>
      </tr>)}</tbody>
    </table> : null}
    {pages>1 ? <nav className={styles.pagination} aria-label={label+" – sider"}>
      <Button type="button" variant="secondary" disabled={currentPage===0} onClick={()=>setPage(Math.max(0,currentPage-1))}>Forrige felt</Button>
      <span>Side {currentPage+1} av {pages}</span>
      <Button type="button" variant="secondary" disabled={currentPage+1>=pages} onClick={()=>setPage(Math.min(pages-1,currentPage+1))}>Neste felt</Button>
    </nav> : null}
  </section>;
}
