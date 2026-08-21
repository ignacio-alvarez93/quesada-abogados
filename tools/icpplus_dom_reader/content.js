(() => {

  const SCHEMA_VERSION = 4;


  const normalize = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();


  const bodyText = normalize(
    document.body
      ? document.body.innerText
      : ""
  );


  function rectOf(element) {

    if (!element) {
      return null;
    }

    const rect =
      element.getBoundingClientRect();

    return {
      x:
        Math.round(rect.x),

      y:
        Math.round(rect.y),

      width:
        Math.round(rect.width),

      height:
        Math.round(rect.height),

      centerX:
        Math.round(
          rect.x +
          rect.width / 2
        ),

      centerY:
        Math.round(
          rect.y +
          rect.height / 2
        ),

      visible:
        rect.width > 0 &&
        rect.height > 0 &&
        rect.bottom >= 0 &&
        rect.right >= 0 &&
        rect.top <= window.innerHeight &&
        rect.left <= window.innerWidth
    };
  }


  function describeControl(selector) {

    const element =
      document.querySelector(
        selector
      );

    if (!element) {
      return null;
    }

    return {
      selector,

      tag:
        element.tagName,

      id:
        element.id || null,

      name:
        element.getAttribute(
          "name"
        ),

      rect:
        rectOf(element)
    };
  }


  const title =
    normalize(document.title);


  const pathname =
    location.pathname;


  // ====================================================
  // PAGE CLASSIFICATION
  // ====================================================

  function detectPage() {

    if (
      /request rejected/i.test(title) ||
      /the requested url was rejected/i.test(bodyText)
    ) {
      return "REQUEST_REJECTED";
    }

    if (
      document.querySelector("#txtHora") ||
      pathname.includes("acOfertarCita")
    ) {
      return "OFFER_APPOINTMENT";
    }

    if (
      document.querySelector("#txtTelefonoCitado") ||
      document.querySelector("#emailUNO")
    ) {
      return "CONTACT_FORM";
    }

    if (
      document.querySelector("#idSede")
    ) {
      return "OFFICE_SELECTION";
    }

    if (
      document.querySelector("#txtIdCitado")
    ) {
      return "IDENTITY_FORM";
    }

    if (
      document.querySelector("#sede") ||
      document.querySelector(
        '[id^="tramiteGrupo"]'
      )
    ) {
      return "PROCEDURE_SELECTION";
    }

    if (
      document.querySelector("select#form")
    ) {
      return "PROVINCE_SELECTION";
    }

    if (
      pathname.includes("/acInfo")
    ) {
      return "PROCEDURE_INFO";
    }

    if (
      pathname.includes("/acValidarEntrada")
    ) {
      return "IDENTITY_VALIDATED";
    }

    if (
      pathname.includes("/index.html") ||
      location.href.includes(
        "/directorio/icpplus"
      )
    ) {
      return "LANDING";
    }

    return "UNKNOWN";
  }


  const page =
    detectPage();


  // ====================================================
  // BLOCKED
  // ====================================================

  function extractSupportId() {

    const match =
      bodyText.match(
        /support\s+id\s+is\s*:?\s*<?(\d+)>?/i
      );

    return match
      ? match[1]
      : null;
  }


  const blocked =
    page === "REQUEST_REJECTED";


  // ====================================================
  // DEGRADED SERVER PAGE
  // ====================================================

  const DEGRADED_PATTERNS = [
    /502\s+bad\s+gateway/i,
    /503\s+service\s+unavailable/i,
    /504\s+gateway\s+time-?out/i,
    /internal\s+server\s+error/i,
    /service\s+temporarily\s+unavailable/i
  ];


  const degraded =
    DEGRADED_PATTERNS.some(
      pattern =>
        pattern.test(title) ||
        pattern.test(bodyText)
    );


  let portalStatus =
    "ONLINE";


  if (blocked) {
    portalStatus =
      "BLOCKED";
  }

  else if (degraded) {
    portalStatus =
      "DEGRADED";
  }


  // ====================================================
  // APPOINTMENTS
  // ====================================================

  const DATE_RE =
    /^\d{1,2}\/\d{1,2}\/\d{4}$/;


  const TIME_RE =
    /^\d{1,2}:\d{2}$/;


  const EXCLUDED_TAGS =
    new Set([
      "SCRIPT",
      "STYLE",
      "NOSCRIPT",
      "OPTION",
      "SELECT",
      "HEAD",
      "META",
      "LINK"
    ]);


  function excluded(element) {

    let current =
      element;

    while (current) {

      if (
        EXCLUDED_TAGS.has(
          current.tagName
        )
      ) {
        return true;
      }

      current =
        current.parentElement;
    }

    return false;
  }


  const tokens = [];


  if (
    page === "OFFER_APPOINTMENT"
  ) {

    const walker =
      document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT
      );


    let node;


    while (
      (node = walker.nextNode())
    ) {

      if (
        excluded(
          node.parentElement
        )
      ) {
        continue;
      }


      const text =
        normalize(
          node.nodeValue
        );


      if (
        DATE_RE.test(text)
      ) {
        tokens.push({
          type: "DATE",
          value: text
        });

        continue;
      }


      if (
        TIME_RE.test(text)
      ) {
        tokens.push({
          type: "TIME",
          value: text
        });
      }
    }
  }


  const appointments = [];

  let pendingDate =
    null;


  for (
    const token
    of tokens
  ) {

    if (
      token.type === "DATE"
    ) {
      pendingDate =
        token.value;

      continue;
    }


    if (
      token.type === "TIME" &&
      pendingDate
    ) {

      appointments.push({
        date:
          pendingDate,

        time:
          token.value
      });

      pendingDate =
        null;
    }
  }


  const seen =
    new Set();


  const uniqueAppointments =
    appointments.filter(
      item => {

        const key =
          `${item.date}|${item.time}`;


        if (
          seen.has(key)
        ) {
          return false;
        }


        seen.add(key);

        return true;
      }
    );


  // ====================================================
  // UNAVAILABLE
  // ====================================================

  // Deliberadamente vacío hasta capturar
  // un mensaje REAL del portal sin citas.
  const KNOWN_UNAVAILABLE_PATTERNS = [];


  const unavailable =
    KNOWN_UNAVAILABLE_PATTERNS.some(
      pattern =>
        pattern.test(bodyText)
    );


  let availabilityStatus =
    "UNKNOWN";


  if (
    uniqueAppointments.length > 0
  ) {
    availabilityStatus =
      "AVAILABLE";
  }

  else if (
    unavailable
  ) {
    availabilityStatus =
      "UNAVAILABLE";
  }


  // ====================================================
  // CATÁLOGOS ÚTILES PARA DIAGNÓSTICO
  // ====================================================

  const horaOptions =
    Array.from(
      document.querySelectorAll(
        "select#txtHora option"
      )
    ).map(
      option => ({
        text:
          normalize(
            option.textContent
          ),

        value:
          option.value
      })
    );


  const officeOptions =
    Array.from(
      document.querySelectorAll(
        "select#idSede option"
      )
    ).map(
      option => ({
        text:
          normalize(
            option.textContent
          ),

        value:
          option.value
      })
    );


  // ====================================================
  // PAYLOAD
  // ====================================================

  const navigationControls = {

    province:
      describeControl(
        "select#form"
      ),

    generalOffice:
      describeControl(
        "select#sede"
      ),

    procedureGroups:
      Array.from(
        document.querySelectorAll(
          'select[id^="tramiteGrupo"]'
        )
      ).map(
        element => ({
          selector:
            "#" +
            CSS.escape(
              element.id
            ),

          id:
            element.id,

          name:
            element.getAttribute(
              "name"
            ),

          rect:
            rectOf(element)
        })
      ),

    identityNie:
      describeControl(
        "#txtIdCitado"
      ),

    identityName:
      describeControl(
        "#txtDesCitado"
      ),

    nationality:
      describeControl(
        "#txtPaisNac"
      ),

    procedureOffice:
      describeControl(
        "#idSede"
      ),

    phone:
      describeControl(
        "#txtTelefonoCitado"
      ),

    email:
      describeControl(
        "#emailUNO"
      ),

    emailRepeat:
      describeControl(
        "#emailDOS"
      )
  };


  const payload = {

    schemaVersion:
      SCHEMA_VERSION,

    eventType:
      "DOM_STATE",

    capturedAt:
      new Date().toISOString(),

    url:
      location.href,

    title,

    pathname,

    page,

    portalStatus,

    availabilityStatus,

    supportId:
      extractSupportId(),

    appointmentCount:
      uniqueAppointments.length,

    appointments:
      uniqueAppointments,

    horaOptions,

    officeOptions,

    navigationControls
  };


  chrome.runtime.sendMessage({
    type:
      "ICP_OBSERVER_EVENT",

    payload
  });

})();
