(() => {
  let week = 0,
    selected = null,
    mode = "preview",
    slots = [],
    sending = false;
  const $ = (s) => document.querySelector(s);
  const todayPL = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Europe/Warsaw" }),
  );
  const friday = new Date(todayPL);
  friday.setHours(12, 0, 0, 0);
  friday.setDate(friday.getDate() + ((5 - friday.getDay() + 7) % 7));
  if (friday.getDay() === todayPL.getDay() && todayPL.getHours() >= 17)
    friday.setDate(friday.getDate() + 7);
  const dateLabel = (d) =>
    d.toLocaleDateString("pl-PL", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  const newId = () =>
    Array.from(crypto.getRandomValues(new Uint8Array(16)), (x) =>
      x.toString(16).padStart(2, "0"),
    ).join("");
  let requestId = newId();
  function slotFor(d, h) {
    return slots.find((iso) => {
      const t = new Date(
        new Date(iso).toLocaleString("en-US", { timeZone: "Europe/Warsaw" }),
      );
      return (
        t.getFullYear() === d.getFullYear() &&
        t.getMonth() === d.getMonth() &&
        t.getDate() === d.getDate() &&
        t.getHours() === h
      );
    });
  }
  function render() {
    const f = new Date(friday);
    f.setDate(f.getDate() + 7 * week);
    const s = new Date(f);
    s.setDate(s.getDate() + 1);
    $("#week-label").textContent = "Wybierz dogodny termin";
    $("#range-label").textContent =
      dateLabel(f) + " – " + dateLabel(s) + " · tydzień " + (week + 1) + " z 5";
    $("#prev").disabled = week === 0;
    $("#next").disabled = week === 4;
    $("#calendar-days").innerHTML = [f, s]
      .map(
        (d, i) =>
          '<div class="calendar-day"><h3>' +
          ["Piątek", "Sobota"][i] +
          '</h3><div class="date">' +
          dateLabel(d) +
          "</div>" +
          [15, 16, 17]
            .map((h) => {
              let available = i === 0 && h > 15;
              const dt = new Date(d);
              dt.setHours(h, 0, 0, 0);
              if (dt <= todayPL) available = false;
              const iso = mode === "live" ? slotFor(d, h) : "";
              if (mode === "live" && !iso) available = false;
              if (mode === "error") available = false;
              const key =
                dt.getFullYear() +
                "-" +
                dt.getMonth() +
                "-" +
                dt.getDate() +
                "-" +
                h;
              const chosen = selected?.key === key;
              return (
                '<button type="button" class="hour ' +
                (chosen ? "selected" : "") +
                '" ' +
                (!available ? "disabled" : "") +
                ' data-key="' +
                key +
                '" data-hour="' +
                h +
                '"><strong>' +
                h +
                ":00</strong><span>" +
                (chosen ? "Wybrany" : available ? "Dostępne" : "Niedostępne") +
                "</span></button>"
              );
            })
            .join("") +
          "</div>",
      )
      .join("");
    document.querySelectorAll(".hour:not(:disabled)").forEach(
      (b) =>
        (b.onclick = () => {
          selected = {
            key: b.dataset.key,
            hour: b.dataset.hour,
            date: f,
            iso: slotFor(f, +b.dataset.hour),
          };
          requestId = newId();
          $("#chosen").textContent =
            "Wybrany termin: piątek, " +
            dateLabel(f) +
            ", godz. " +
            selected.hour +
            ":00 · 30 minut · 600 zł";
          $("#submit-reservation").disabled = false;
          render();
        }),
    );
  }
  $("#prev").onclick = () => {
    week--;
    render();
  };
  $("#next").onclick = () => {
    week++;
    render();
  };
  $("#reservation-form").addEventListener("input", () => {
    requestId = newId();
  });
  $("#reservation-form").onsubmit = async (e) => {
    e.preventDefault();
    if (!selected || sending) return;
    let ref = "";
    const btn = $("#submit-reservation");
    if (mode === "live") {
      sending = true;
      btn.disabled = true;
      btn.textContent = "Wysyłanie zgłoszenia…";
      const f = new FormData(e.target);
      try {
        const r = await fetch("/api/book", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: f.get("name"),
            email: f.get("email"),
            phone: f.get("phone"),
            questions: f.get("questions"),
            website: f.get("website"),
            slot: selected.iso,
            request_id: requestId,
            terms: true,
          }),
        });
        const data = await r.json();
        if (!r.ok)
          throw Error(data.error || "Nie udało się przyjąć rezerwacji.");
        ref = data.id;
        slots = slots.filter((x) => x !== selected.iso);
        render();
      } catch (err) {
        $("#chosen").textContent =
          err.message + " W razie wątpliwości zadzwoń: 577 169 800.";
        return;
      } finally {
        sending = false;
        btn.disabled = false;
        btn.textContent = "Zarezerwuj wstępnie termin →";
      }
    }
    $("#reservation-form").hidden = true;
    $("#confirmation").hidden = false;
    $("#confirmation").innerHTML =
      "<h3>" +
      (mode === "live"
        ? "Otrzymaliśmy rezerwację wstępną"
        : "Podgląd potwierdzenia rezerwacji") +
      "</h3><p><strong>Piątek, " +
      dateLabel(selected.date) +
      ", godz. " +
      selected.hour +
      ':00</strong><br>Konsultacja onkologiczna online · 30 minut · 600 zł.</p><p>Po otrzymaniu zgłoszenia asystentka oddzwoni w najbliższym możliwym terminie, aby potwierdzić konsultację oraz przekazać informacje dotyczące płatności i przygotowania dokumentacji.</p><p>Możesz również zadzwonić bezpośrednio: <a href="tel:+48577169800">577 169 800</a>, codziennie 8:00–17:00.</p>' +
      (mode === "live"
        ? "<p>Numer zgłoszenia: <strong>" +
          ref +
          "</strong>. Wiadomość potwierdzająca zostanie wysłana na podany adres e-mail. Jeśli nie dotrze, skontaktuj się z asystentką.</p>"
        : '<p class="preview-disclaimer">To wyłącznie podgląd. Termin nie został zarezerwowany. Nie wysłano e-maili ani SMS-ów i nie zapisano danych.</p><button type="button" class="btn-light" id="again">Wróć do formularza</button>');
    $("#again")?.addEventListener("click", () => {
      $("#confirmation").hidden = true;
      $("#reservation-form").hidden = false;
    });
    $("#confirmation").focus();
  };
  render();
  if (location.protocol !== "file:") {
    fetch("/api/availability", { cache: "no-store" })
      .then((r) => {
        if (r.status === 404) return { mode: "preview" };
        if (!r.ok) throw Error();
        return r.json();
      })
      .then((data) => {
        if (data.mode === "live") {
          mode = "live";
          slots = data.slots;
          document
            .querySelectorAll(".preview-strip,.preview-disclaimer")
            .forEach((e) => e.remove());
          render();
        }
      })
      .catch(() => {
        mode = "error";
        $("#chosen").textContent =
          "Rezerwacja online jest chwilowo niedostępna. Zadzwoń: 577 169 800.";
        render();
      });
  }
})();
