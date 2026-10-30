/** @jsxImportSource react */
import { Button, Modal } from "@canonical/react-components"
import { createRoot } from "react-dom/client"
import { renderToStaticMarkup } from "react-dom/server"
import { flushSync } from "react-dom"

export type ActionOptions = { icon?: string; primary?: boolean; danger?: boolean; disabled?: boolean; title?: string }
// Controller adapters toggle the native disabled property after rendering.
// Avoid leaving Canonical static disabled attributes/classes behind on enable.
export function actionButton(label: string, action: string, options: ActionOptions = {}): string {
  return renderToStaticMarkup(<Button type="button" className={`native-button${options.primary ? " primary" : ""}${options.danger ? " danger" : ""}`}
    appearance={options.danger ? "negative" : options.primary ? "positive" : undefined}
    data-action={action} disabled={options.disabled} title={options.title}>
    {options.icon && <span aria-hidden="true">{options.icon}</span>}{label}
  </Button>).replace(' aria-disabled="true"', "").replace(" is-disabled", "")
}

type DialogField = { name: string; label: string; value?: string; placeholder?: string; type?: "text" | "number" | "textarea"; required?: boolean; help?: string }
export type FormDialogOptions = { title: string; detail?: string; fields: DialogField[]; submitLabel?: string; danger?: boolean; wide?: boolean }
export function formDialog(options: FormDialogOptions): Promise<Record<string,string> | null> {
  return new Promise(resolve => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const host = document.createElement("div")
    document.body.append(host)
    const root = createRoot(host)
    let closed = false
    const close = (value: Record<string,string> | null) => {
      if (closed) return
      closed = true
      // Do not unmount a React tree synchronously during its event dispatch.
      queueMicrotask(() => {
        root.unmount()
        host.remove()
        if (previous?.isConnected) previous.focus()
        resolve(value)
      })
    }
    flushSync(() => root.render(<Modal title={options.title} close={() => close(null)} closeOnOutsideClick
      className={`lsm-modal${options.wide ? " wide" : ""}`}>
      <form onSubmit={event => {
        event.preventDefault()
        close(Object.fromEntries([...new FormData(event.currentTarget).entries()].map(([key,value]) => [key,String(value)])))
      }}>
        {options.detail && <p>{options.detail}</p>}
        {options.fields.map(field => <label className="native-field" key={field.name}>
          <span>{field.label}</span>
          {field.type === "textarea" ? <textarea aria-label={field.label} name={field.name} defaultValue={field.value} placeholder={field.placeholder} required={field.required} />
            : <input aria-label={field.label} name={field.name} type={field.type || "text"} defaultValue={field.value} placeholder={field.placeholder} required={field.required} />}
          {field.help && <small>{field.help}</small>}
        </label>)}
        <div className="dialog-actions"><Button type="button" onClick={() => close(null)}>Cancel</Button><Button type="submit" appearance={options.danger ? "negative" : "positive"}>{options.submitLabel || "Save"}</Button></div>
      </form>
    </Modal>))
    host.querySelector<HTMLElement>("input,textarea,select,button[type=submit]")?.focus()
  })
}
