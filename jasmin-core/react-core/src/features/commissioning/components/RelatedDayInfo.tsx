import dayjs from "dayjs";

import { useDateFormat } from "@hooks/index";

interface RelatedDayInfoProps {
  label: string;
  relatedDayNumbers: number[];
  selectedWeek: number;
  selectedYear: number;
  // Optional custom formatter — e.g. packing dates need a week adjustment when
  // packing happens the week before delivery. Falls back to the plain
  // isoWeekday date in the selected week.
  formatDate?: (day: number) => string;
}

export default function RelatedDayInfo({
  label,
  relatedDayNumbers,
  selectedWeek,
  selectedYear,
  formatDate,
}: RelatedDayInfoProps) {
  const { dateFormat } = useDateFormat();
  const defaultFormatDate = (dayNumber: number) => {
    const date = dayjs()
      .year(selectedYear)
      .isoWeek(selectedWeek)
      .isoWeekday(dayNumber + 1);
    return date.format(`dddd, ${dateFormat}`);
  };
  const format = formatDate ?? defaultFormatDate;

  return (
    <div className="imitating-bold-select" style={{marginTop: "1em"}}>
      {label}
      {relatedDayNumbers.map((day, index) => (
        <span key={day}>
          {index > 0 && " / "}
          {format(day)}
        </span>
      ))}
    </div>
  );
}
