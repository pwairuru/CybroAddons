import { SaverScreen } from "@point_of_sale/app/screens/saver_screen/saver_screen";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { patch } from "@web/core/utils/patch";

// Expose the POS store on the lock screen so the debrand template can use the POS config logo.
patch(SaverScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
    },
});
