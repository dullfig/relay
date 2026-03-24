; Fibonacci sequence on the relay computer
; Displays successive Fibonacci numbers on the nixie tubes
;
; Uses BCD arithmetic - each number is 8 nibbles (8 digits)
; Stores two values in zero page, adds them, displays result
;
; Zero page usage:
;   $00-$07  fib_prev (8 BCD digits, LSB first)
;   $08-$0F  fib_curr (8 BCD digits, LSB first)
;   $10-$17  temp (8 BCD digits)

.equ NIXIE $FF2

.org $100

start:
        ; Initialize: prev = 0, curr = 1
        LDA #0
        STA $00             ; prev digit 0 = 0
        STA $01
        STA $02
        STA $03
        STA $04
        STA $05
        STA $06
        STA $07             ; prev = 00000000

        LDA #1
        STA $08             ; curr digit 0 = 1
        LDA #0
        STA $09
        STA $0A
        STA $0B
        STA $0C
        STA $0D
        STA $0E
        STA $0F             ; curr = 00000001

; Main loop: display curr, then compute next = curr + prev
fib_loop:
        ; Display curr on nixies (8 nibbles -> 8 digits)
        LDA $0F             ; most significant digit first
        STA NIXIE
        LDA $0E
        STA NIXIE
        LDA $0D
        STA NIXIE
        LDA $0C
        STA NIXIE
        LDA $0B
        STA NIXIE
        LDA $0A
        STA NIXIE
        LDA $09
        STA NIXIE
        LDA $08
        STA NIXIE           ; least significant

        ; Add: temp = curr + prev (BCD)
        SED                 ; BCD mode
        CLC                 ; clear carry for addition
        LDX #0              ; digit index

add_loop:
        LDA $00,X           ; load prev[X]
        ADD $08,X           ; add curr[X] (with carry)
        STA $10,X           ; store to temp[X]
        INC                 ; next digit (X++)
        ; TODO: need INX instruction, or use INC on a ZP counter
        ; For now this is pseudocode - the real version needs
        ; a proper loop counter mechanism
        CMP #8
        BNE add_loop

        ; Shift: prev = curr, curr = temp
        LDX #0
copy_loop:
        LDA $08,X           ; curr -> prev
        STA $00,X
        LDA $10,X           ; temp -> curr
        STA $08,X
        INC
        CMP #8
        BNE copy_loop

        CLD                 ; back to binary mode
        JMP fib_loop        ; display and repeat forever
