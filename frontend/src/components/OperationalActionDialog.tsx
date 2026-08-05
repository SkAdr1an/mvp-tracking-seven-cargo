import { FormEvent, ReactNode, useEffect, useId, useRef, useState } from 'react'
import { X } from 'lucide-react'

export type OperationalDialogField = {
  name: string
  label: string
  type?: 'text' | 'textarea' | 'datetime-local' | 'select'
  initialValue?: string
  options?: Array<{ value: string; label: string }>
  minLength?: number
  hint?: string
}

export function OperationalActionDialog({
  title, description, context, fields, confirmLabel, danger = false, pending, error, onCancel, onConfirm,
}: {
  title: string
  description: string
  context: ReactNode
  fields: OperationalDialogField[]
  confirmLabel: string
  danger?: boolean
  pending: boolean
  error?: string
  onCancel: () => void
  onConfirm: (values: Record<string, string>) => void
}) {
  const titleId = useId()
  const dialogRef = useRef<HTMLFormElement>(null)
  const firstField = useRef<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(null)
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.map((field) => [field.name, field.initialValue || ''])))
  const [validation, setValidation] = useState('')

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    firstField.current?.focus()
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !pending) onCancel()
      if (event.key === 'Tab') {
        const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])') || [])
        if (!focusable.length) return
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('keydown', escape)
      document.body.style.overflow = previousOverflow
      previouslyFocused?.focus()
    }
  }, [onCancel, pending])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const invalid = fields.find((field) => (values[field.name] || '').trim().length < (field.minLength ?? 1))
    if (invalid) {
      setValidation(`Preencha “${invalid.label}” corretamente.`)
      return
    }
    setValidation('')
    onConfirm(Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value.trim()])))
  }

  return <div className="operational-dialog-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !pending) onCancel()
  }}>
    <form ref={dialogRef} className="operational-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} onSubmit={submit}>
      <header>
        <div><span className="eyebrow">Confirmação operacional</span><h2 id={titleId}>{title}</h2></div>
        <button type="button" className="operational-dialog__close" onClick={onCancel} disabled={pending} aria-label="Cancelar e fechar"><X size={20}/></button>
      </header>
      <p>{description}</p>
      <div className="operational-dialog__context">{context}</div>
      <div className="operational-dialog__fields">
        {fields.map((field, index) => <label key={field.name}>
          <span>{field.label}</span>
          {field.type === 'select'
            ? <select ref={index === 0 ? firstField as React.RefObject<HTMLSelectElement> : undefined} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}>
                <option value="">Selecione</option>{field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            : field.type === 'textarea'
              ? <textarea ref={index === 0 ? firstField as React.RefObject<HTMLTextAreaElement> : undefined} rows={4} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}/>
              : <input ref={index === 0 ? firstField as React.RefObject<HTMLInputElement> : undefined} type={field.type || 'text'} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}/>}
          {field.hint && <small>{field.hint}</small>}
        </label>)}
      </div>
      {(validation || error) && <div className="form-error" role="alert">{validation || error}</div>}
      <footer>
        <button type="button" className="secondary-button" onClick={onCancel} disabled={pending}>Cancelar</button>
        <button className={danger ? 'danger-button' : 'primary-button'} disabled={pending}>{pending ? 'Salvando...' : confirmLabel}</button>
      </footer>
    </form>
  </div>
}
