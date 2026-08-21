(() => {
  const normalize = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();


  function detectPage() {
    const body = normalize(
      document.body
        ? document.body.innerText
        : ""
    );

    if (
      /request rejected/i.test(document.title) ||
      /the requested url was rejected/i.test(body)
    ) {
      return "REQUEST_REJECTED";
    }

    if (
      document.querySelector("#txtHora") ||
      location.pathname.includes("acOfertarCita")
    ) {
      return "OFFER_APPOINTMENT";
    }

    if (
      document.querySelector("#txtTelefonoCitado") ||
      document.querySelector("#emailUNO")
    ) {
      return "CONTACT_FORM";
    }

    if (document.querySelector("#idSede")) {
      return "OFFICE_SELECTION";
    }

    if (document.querySelector("#txtIdCitado")) {
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

    if (document.querySelector("select#form")) {
      return "PROVINCE_SELECTION";
    }

    if (
      location.pathname.includes(
        "acValidarEntrada"
      )
    ) {
      return "IDENTITY_VALIDATED";
    }

    if (
      location.pathname.includes(
        "acInfo"
      )
    ) {
      return "PROCEDURE_INFO";
    }

    return "LANDING";
  }


  function rectOf(element) {
    if (!element) {
      return null;
    }

    const r =
      element.getBoundingClientRect();

    /*
      DOM coordinates are relative to the content viewport.
      Estimate the current Chrome content origin on screen.
      This removes the F11 dependency.
    */

    const borderX =
      Math.max(
        0,
        (
          window.outerWidth -
          window.innerWidth
        ) / 2
      );

    const chromeTop =
      Math.max(
        0,
        (
          window.outerHeight -
          window.innerHeight
        ) - borderX
      );

    const centerX =
      r.x + r.width / 2;

    const centerY =
      r.y + r.height / 2;

    return {
      x:
        Math.round(r.x),

      y:
        Math.round(r.y),

      width:
        Math.round(r.width),

      height:
        Math.round(r.height),

      centerX:
        Math.round(centerX),

      centerY:
        Math.round(centerY),

      viewportWidth:
        window.innerWidth,

      viewportHeight:
        window.innerHeight,

      devicePixelRatio:
        window.devicePixelRatio,

      screenCenterX:
        Math.round(
          window.screenX +
          borderX +
          centerX
        ),

      screenCenterY:
        Math.round(
          window.screenY +
          chromeTop +
          centerY
        ),

      visible:
        r.width > 0 &&
        r.height > 0 &&
        r.bottom >= 0 &&
        r.right >= 0 &&
        r.top <= window.innerHeight &&
        r.left <= window.innerWidth
    };
  }


  function basicControl(
    element,
    selector
  ) {
    if (!element) {
      return null;
    }

    return {
      selector,

      id:
        element.id || null,

      name:
        element.getAttribute("name"),

      tag:
        element.tagName,

      value:
        "value" in element
          ? element.value
          : null,

      focused:
        document.activeElement === element,

      rect:
        rectOf(element)
    };
  }


  function describe(selector) {
    return basicControl(
      document.querySelector(selector),
      selector
    );
  }


  function describeSelectElement(
    element,
    selector
  ) {
    if (!element) {
      return null;
    }

    return {
      ...basicControl(
        element,
        selector
      ),

      selectedIndex:
        element.selectedIndex,

      selectedValue:
        element.value,

      selectedText:
        element.selectedIndex >= 0
          ? normalize(
              element.options[
                element.selectedIndex
              ]?.textContent
            )
          : null,

      options:
        Array.from(
          element.options
        ).map(
          (option, index) => ({
            index,

            text:
              normalize(
                option.textContent
              ),

            value:
              option.value,

            disabled:
              !!option.disabled,

            selected:
              !!option.selected
          })
        )
    };
  }


  function describeSelect(selector) {
    return describeSelectElement(
      document.querySelector(selector),
      selector
    );
  }


  function buildNavigationControls() {

    const procedureGroups =
      Array.from(
        document.querySelectorAll(
          'select[id^="tramiteGrupo"]'
        )
      ).map(
        element =>
          describeSelectElement(
            element,
            "#" + CSS.escape(element.id)
          )
      );

    return {
      province:
        describeSelect("#form"),

      generalOffice:
        describeSelect("#sede"),

      procedureGroups,

      identityNie:
        describe("#txtIdCitado"),

      identityName:
        describe("#txtDesCitado"),

      nationality:
        describeSelect("#txtPaisNac"),

      procedureOffice:
        describeSelect("#idSede"),

      phone:
        describe("#txtTelefonoCitado"),

      email:
        describe("#emailUNO"),

      emailRepeat:
        describe("#emailDOS")
    };
  }


  function buildActionControls() {

    return Array.from(
      document.querySelectorAll(
        [
          "button",
          "input[type=submit]",
          "input[type=button]",
          "input[type=image]",
          "#btnEntrar",
          "a",
          "[role=button]"
        ].join(",")
      )
    ).map(
      (element, index) => ({
        index,

        id:
          element.id || null,

        name:
          element.getAttribute("name"),

        tag:
          element.tagName,

        type:
          element.getAttribute("type"),

        text:
          normalize(
            element.tagName === "INPUT"
              ? element.value
              : element.textContent
          ),

        rect:
          rectOf(element)
      })
    );
  }


  function emit() {

    // IMPORTANTE:
    // recalcular geometría en CADA emisión.
    const navigationControls =
      buildNavigationControls();

    const actionControls =
      buildActionControls();
    chrome.runtime.sendMessage({
      type:
        "ICP_OBSERVER_EVENT",

      payload: {
        schemaVersion: 6,

        eventType:
          "SEMANTIC_STATE",

        capturedAt:
          new Date().toISOString(),

        url:
          location.href,

        page:
          detectPage(),

        viewport: {
          screenX:
            window.screenX,

          screenY:
            window.screenY,

          outerWidth:
            window.outerWidth,

          outerHeight:
            window.outerHeight,

          innerWidth:
            window.innerWidth,

          innerHeight:
            window.innerHeight,

          devicePixelRatio:
            window.devicePixelRatio
        },

        navigationControls,

        actionControls
      }
    });
  }


  emit();


  /*
    Si cambia tamaño/scroll, volvemos a publicar geometría.
  */

  let timer = null;

  function scheduleEmit() {
    clearTimeout(timer);

    timer = setTimeout(
      emit,
      150
    );
  }

  window.addEventListener(
    "resize",
    scheduleEmit
  );

  window.addEventListener(
    "scroll",
    scheduleEmit,
    {
      passive: true,
      capture: true
    }
  );


  // Heartbeat semántico.
  // Permite recalcular geometría aunque una página
  // no propague de forma fiable resize/scroll.
  setInterval(
    emit,
    750
  );
})();
