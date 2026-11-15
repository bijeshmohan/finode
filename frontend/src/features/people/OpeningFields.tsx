// Who owes whom, the amount and since when: the opening balance's fields, on the person form and the opening balance
// form (person_form.html, person_opening.html).
import { useGrouping, usePlaces } from "../../app/currency";
import { AmountField } from "../../components/AmountField";
import form from "../../components/Forms.module.css";

export type Direction = "receivable" | "payable";

interface FieldsProps {
  /** The two choices' words; none when who owes whom can no longer change. */
  choices: [string, string] | null;
  direction: Direction;
  onDirection: (direction: Direction) => void;
  amount: string;
  onAmount: (amount: string) => void;
  since: string;
  onSince: (day: string) => void;
}

export function OpeningFields({ choices, direction, onDirection, amount, onAmount, since, onSince }: FieldsProps) {
  const grouping = useGrouping();
  const places = usePlaces();
  return (
    <>
      {choices && (
        <div className={form.seg} role="radiogroup" aria-label="Who owes whom">
          {(["receivable", "payable"] as const).map((d, i) => (
            <label key={d}>
              <input
                type="radio"
                name="opening_direction"
                checked={direction === d}
                onChange={() => {
                  onDirection(d);
                }}
              />
              <span>{choices[i]}</span>
            </label>
          ))}
        </div>
      )}
      <AmountField
        id="opening-amount"
        label="Amount"
        value={amount}
        onChange={onAmount}
        places={places}
        grouping={grouping}
      />
      <label>
        Since
        <input
          type="date"
          value={since}
          onChange={(event) => {
            onSince(event.target.value);
          }}
        />
      </label>
    </>
  );
}
