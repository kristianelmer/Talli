"use client";

import {
  Button,
  FormField,
  SubmitButton,
  ToastProvider,
  useToast,
} from "../components/ui";

function ToastButtons() {
  const { toast } = useToast();
  return (
    <div className="uiRow">
      <Button
        variant="secondary"
        onClick={() =>
          toast({
            variant: "success",
            title: "Lagret",
            description: "Endringene dine er lagret.",
          })
        }
      >
        Vis suksess-varsel
      </Button>
      <Button
        variant="secondary"
        onClick={() =>
          toast({
            variant: "danger",
            title: "Noe gikk galt",
            description: "Kunne ikke lagre. Prøv igjen.",
          })
        }
      >
        Vis feilvarsel
      </Button>
    </div>
  );
}

async function fakeSave() {
  await new Promise((resolve) => setTimeout(resolve, 1200));
}

/** Interactive demos that require a client boundary (toast, validation, pending). */
export function ClientDemos() {
  return (
    <ToastProvider>
      <ToastButtons />
      <div className="uiStack">
        <FormField
          label="Organisasjonsnummer"
          name="demo-orgnr"
          inputMode="numeric"
          placeholder="9 siffer"
          helper="Vi sjekker formatet mens du skriver."
          validate={(value) =>
            value && !/^\d{9}$/.test(value.replace(/\s/g, ""))
              ? "Org.nr må være 9 siffer."
              : undefined
          }
        />
        <form action={fakeSave}>
          <SubmitButton pendingLabel="Lagrer …">Lagre (demo)</SubmitButton>
        </form>
      </div>
    </ToastProvider>
  );
}
